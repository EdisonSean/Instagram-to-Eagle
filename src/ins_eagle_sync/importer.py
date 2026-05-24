from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .eagle_client import EagleApiError, EagleClient
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


def import_staging_items(
    items: list[ImportItem],
    *,
    eagle: EagleClient,
    state: ImportedState,
    folder_id: str,
    dry_run: bool = False,
    force: bool = False,
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
            result.skipped += 1
            log(f"skip already imported: {item.unique_key}")
            continue
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


def extract_eagle_item_id(response: dict[str, Any]) -> str:
    data = response.get("data") if isinstance(response, dict) else None
    if isinstance(data, dict):
        for key in ("id", "itemId", "item_id"):
            if data.get(key):
                return str(data[key])

    for key in ("id", "itemId", "item_id"):
        if response.get(key):
            return str(response[key])

    return ""


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
