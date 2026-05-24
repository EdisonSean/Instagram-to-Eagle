from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .eagle_client import EagleApiError, EagleClient, extract_eagle_item_id
from .metadata_parser import ImportItem
from .state_store import ImportedState


LogFn = Callable[[str], None]


@dataclass(frozen=True)
class ImportFailure:
    unique_key: str
    title: str
    error: str


@dataclass
class ImportResult:
    total: int = 0
    skipped: int = 0
    imported: int = 0
    failed: int = 0
    failures: list[ImportFailure] = field(default_factory=list)


@dataclass
class VerifyImportsResult:
    checked: int = 0
    alive: int = 0
    missing: int = 0
    unknown: int = 0
    removed: int = 0
    missing_keys: list[str] = field(default_factory=list)


def import_staging_items(
    items: list[ImportItem],
    *,
    eagle: EagleClient,
    state: ImportedState,
    folder_id: str,
    dry_run: bool = False,
    force: bool = False,
    verify_eagle: bool = False,
    show_annotation: bool = False,
    log: LogFn = print,
) -> ImportResult:
    result = ImportResult(total=len(items))
    log(f"ImportItems found: {result.total}")

    if dry_run:
        _log_dry_run_plan(items, state=state, force=force, show_annotation=show_annotation, result=result, log=log)
        _log_summary(result, dry_run=True, log=log)
        return result

    pending_items: list[ImportItem] = []
    for item in items:
        if state.has_unique_key(item.unique_key) and not force:
            if not verify_eagle:
                result.skipped += 1
                log(f"skip already imported: {item.unique_key}")
                continue

            eagle_item_id = str(state.records.get(item.unique_key, {}).get("eagle_item_id") or "")
            if not eagle_item_id:
                try:
                    eagle_item_id = eagle.find_matching_item_id(item, folder_id)
                except EagleApiError as exc:
                    result.skipped += 1
                    log(
                        f"warning: could not recover Eagle item id for {item.unique_key}: "
                        f"{exc}; skip to avoid duplicate import."
                    )
                    continue

                if eagle_item_id:
                    state.records[item.unique_key]["eagle_item_id"] = eagle_item_id
                    state.save()
                    result.skipped += 1
                    log(f"skip existing Eagle item after recovering id: {item.unique_key}")
                    continue

                state.remove_keys([item.unique_key], save=True)
                log(f"removed stale imported_state record with no matching Eagle item: {item.unique_key}")
                pending_items.append(item)
                continue

            try:
                exists = eagle.item_exists(eagle_item_id)
            except EagleApiError as exc:
                result.skipped += 1
                log(
                    f"warning: could not verify Eagle item {eagle_item_id} for {item.unique_key}: "
                    f"{exc}; skip to avoid duplicate import."
                )
                continue

            if exists is True:
                result.skipped += 1
                log(f"skip existing Eagle item: {item.unique_key}")
                continue

            if exists is not False:
                result.skipped += 1
                log(
                    f"warning: Eagle item status is unknown for {item.unique_key} "
                    f"({eagle_item_id}); skip to avoid duplicate import."
                )
                continue

            state.remove_keys([item.unique_key], save=True)
            log(f"removed stale imported_state record: {item.unique_key}")
        pending_items.append(item)

    if not pending_items:
        _log_summary(result, dry_run=False, log=log)
        return result

    try:
        eagle.check_app_available()
    except EagleApiError as exc:
        error = str(exc)
        result.failed = len(pending_items)
        result.failures = [ImportFailure(item.unique_key, item.title, error) for item in pending_items]
        log(f"error: {error}")
        _log_summary(result, dry_run=False, log=log)
        return result

    for item in pending_items:
        try:
            response = eagle.add_item_from_path(item, folder_id)
            eagle_item_id = extract_eagle_item_id(response)
            if not eagle_item_id:
                log(
                    f"warning: Eagle API response did not include an item id for {item.unique_key}; "
                    "future --verify-eagle runs will skip this state record."
                )
            state.mark_item_imported(item, eagle_item_id=eagle_item_id)
            state.save()
            result.imported += 1
            log(f"imported: {item.unique_key}")
        except Exception as exc:  # noqa: BLE001 - keep import batch running with clear per-item errors.
            result.failed += 1
            failure = ImportFailure(item.unique_key, item.title, str(exc))
            result.failures.append(failure)
            log(f"failed: {item.unique_key}: {failure.error}")

    _log_summary(result, dry_run=False, log=log)
    return result


def verify_import_records(
    *,
    eagle: EagleClient,
    state: ImportedState,
    unique_key: str | None = None,
    shortcode: str | None = None,
    username: str | None = None,
    dry_run: bool = False,
    log: LogFn = print,
) -> VerifyImportsResult:
    keys = state.find_keys(unique_key=unique_key, shortcode=shortcode, username=username)
    result = VerifyImportsResult(checked=len(keys))

    for key in keys:
        record = state.records.get(key, {})
        eagle_item_id = str(record.get("eagle_item_id") or "")
        if not eagle_item_id:
            result.unknown += 1
            log(f"warning: imported_state has no eagle_item_id: {key}")
            continue

        try:
            exists = eagle.item_exists(eagle_item_id)
        except EagleApiError as exc:
            result.unknown += 1
            log(f"warning: could not verify Eagle item {eagle_item_id} for {key}: {exc}")
            continue

        if exists is True:
            result.alive += 1
            log(f"alive: {key}")
            continue

        if exists is not False:
            result.unknown += 1
            log(f"warning: Eagle item status is unknown for {key}: {eagle_item_id}")
            continue

        result.missing += 1
        result.missing_keys.append(key)
        action = "would remove" if dry_run else "missing"
        log(f"{action}: {key}")

    if not dry_run and result.missing_keys:
        removed_keys = state.remove_keys(result.missing_keys, save=True)
        result.removed = len(removed_keys)
    elif dry_run:
        result.removed = 0

    log(f"checked: {result.checked}")
    log(f"alive: {result.alive}")
    log(f"missing: {result.missing}")
    log(f"unknown: {result.unknown}")
    log(f"removed: {result.removed}")
    return result


def _log_dry_run_plan(
    items: list[ImportItem],
    *,
    state: ImportedState,
    force: bool,
    show_annotation: bool,
    result: ImportResult,
    log: LogFn,
) -> None:
    for item in items:
        already_imported = state.has_unique_key(item.unique_key)
        action = "import"
        if already_imported and not force:
            action = "skip already imported"
            result.skipped += 1

        log(f"[dry-run] {action}: {item.title}")
        log(f"  website: {item.website}")
        log(f"  tags: {', '.join(item.tags)}")
        log(f"  unique_key: {item.unique_key}")
        if show_annotation:
            log("  annotation:")
            log(item.annotation)


def _log_summary(result: ImportResult, *, dry_run: bool, log: LogFn) -> None:
    log(f"dry-run: {dry_run}")
    log(f"total: {result.total}")
    log(f"skipped: {result.skipped}")
    log(f"imported: {result.imported}")
    log(f"failed: {result.failed}")
