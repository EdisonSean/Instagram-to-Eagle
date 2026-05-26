from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .config import AppConfig
from .eagle_client import EagleClient
from .gallerydl_runner import build_gallery_dl_request, run_gallery_dl
from .importer import import_staging_items, verify_import_records
from .metadata_parser import ImportItem, scan_staging_dir
from .state_store import ImportedState
from .utils import detect_instagram_url


LogFn = Callable[[str], None]


def parse_staging(config: AppConfig, staging_dir: str | Path) -> dict[str, Any]:
    items = scan_staging_dir(Path(staging_dir), title_caption_chars=config.title_caption_chars)
    return {
        "ok": True,
        "total": len(items),
        "items": [_item_summary(item) for item in items],
        "messages": [],
    }


def import_staging(
    config: AppConfig,
    staging_dir: str | Path,
    *,
    folder_id: str | None = None,
    folder_path: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    verify_eagle: bool = False,
    show_annotation: bool = False,
    log: LogFn | None = None,
) -> dict[str, Any]:
    messages: list[str] = []
    logger = _logger(messages, log)
    items = scan_staging_dir(Path(staging_dir), title_caption_chars=config.title_caption_chars)
    eagle = EagleClient(config.eagle_api_base)
    resolved_folder_id = resolve_target_folder_id(
        folder_id=folder_id,
        folder_path=folder_path,
        eagle=eagle,
        dry_run=dry_run,
        log=logger,
    )
    if resolved_folder_id is None:
        return _service_result(False, messages=messages)

    state = ImportedState.load(config.imported_state)
    result = import_staging_items(
        items,
        eagle=eagle,
        state=state,
        folder_id=resolved_folder_id,
        dry_run=dry_run,
        force=force,
        verify_eagle=verify_eagle,
        show_annotation=show_annotation,
        log=logger,
    )
    return _import_result_to_service(result, messages)


def sync_post(
    config: AppConfig,
    post_url: str,
    *,
    folder_id: str | None = None,
    folder_path: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    verify_eagle: bool = False,
    show_annotation: bool = False,
    ignore_archive: bool = False,
    verbose_gallery_dl: bool = False,
    log: LogFn | None = None,
) -> dict[str, Any]:
    messages: list[str] = []
    logger = _logger(messages, log)
    info = detect_instagram_url(post_url)
    if info.mode.value != "post":
        logger("sync-post requires a post or reel URL.")
        return _service_result(False, messages=messages)

    request = build_gallery_dl_request(
        config,
        info.normalized_url,
        ignore_archive=ignore_archive,
        verbose=verbose_gallery_dl,
    )
    download_result = run_gallery_dl(
        config,
        info.normalized_url,
        dry_run=dry_run,
        ignore_archive=ignore_archive,
        verbose=verbose_gallery_dl,
        log=logger,
    )
    if download_result is not None and download_result.returncode != 0:
        return _service_result(False, messages=messages, returncode=download_result.returncode)

    items = scan_staging_dir(request.target_dir, title_caption_chars=config.title_caption_chars)
    empty_result = _fail_if_no_downloaded_items(
        items,
        request.target_dir,
        dry_run=dry_run,
        download_ran=download_result is not None,
        messages=messages,
        log=logger,
    )
    if empty_result is not None:
        return empty_result

    return _import_from_items(
        config,
        items,
        folder_id=folder_id,
        folder_path=folder_path,
        dry_run=dry_run,
        force=force,
        verify_eagle=verify_eagle,
        show_annotation=show_annotation,
        messages=messages,
        log=logger,
    )


def sync_author(
    config: AppConfig,
    author_url: str,
    *,
    folder_id: str | None = None,
    folder_path: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    verify_eagle: bool = False,
    max_posts: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    show_annotation: bool = False,
    ignore_archive: bool = False,
    verbose_gallery_dl: bool = False,
    log: LogFn | None = None,
) -> dict[str, Any]:
    messages: list[str] = []
    logger = _logger(messages, log)
    info = detect_instagram_url(author_url)
    if info.mode.value != "author":
        logger("sync-author requires an author URL, e.g. https://www.instagram.com/username/")
        return _service_result(False, messages=messages)
    effective_max_posts = max_posts if max_posts is not None else config.download.max_posts
    if effective_max_posts == 0 or effective_max_posts < -1:
        logger("error: max_posts must be -1 or greater than 0.")
        return _service_result(False, messages=messages)
    try:
        request = build_gallery_dl_request(
            config,
            info.normalized_url,
            ignore_archive=ignore_archive,
            verbose=verbose_gallery_dl,
            max_posts=max_posts,
            date_from=date_from,
            date_to=date_to,
        )
    except ValueError as exc:
        logger(f"error: {exc}")
        return _service_result(False, messages=messages)
    if effective_max_posts == -1:
        logger("作者主页模式：不限制抓取数量")
    else:
        logger(f"作者主页模式：最多抓取 {effective_max_posts} 条")
    if date_from or date_to:
        logger(f"作者主页模式：时间范围 {date_from or '不限'} 到 {date_to or '不限'}")
    download_result = run_gallery_dl(
        config,
        info.normalized_url,
        dry_run=dry_run,
        ignore_archive=ignore_archive,
        verbose=verbose_gallery_dl,
        max_posts=max_posts,
        date_from=date_from,
        date_to=date_to,
        log=logger,
    )
    if download_result is not None and download_result.returncode != 0:
        return _service_result(False, messages=messages, returncode=download_result.returncode)

    items = scan_staging_dir(
        request.target_dir,
        title_caption_chars=config.title_caption_chars,
        preferred_username=info.username,
    )
    empty_result = _fail_if_no_downloaded_items(
        items,
        request.target_dir,
        dry_run=dry_run,
        download_ran=download_result is not None,
        messages=messages,
        log=logger,
    )
    if empty_result is not None:
        return empty_result

    return _import_from_items(
        config,
        items,
        folder_id=folder_id,
        folder_path=folder_path,
        dry_run=dry_run,
        force=force,
        verify_eagle=verify_eagle,
        show_annotation=show_annotation,
        messages=messages,
        log=logger,
    )


def verify_imports(
    config: AppConfig,
    *,
    unique_key: str | None = None,
    shortcode: str | None = None,
    username: str | None = None,
    folder_id: str | None = None,
    folder_path: str | None = None,
    dry_run: bool = False,
    log: LogFn | None = None,
) -> dict[str, Any]:
    messages: list[str] = []
    logger = _logger(messages, log)
    if unique_key and (shortcode or username):
        logger("verify-imports --unique-key cannot be combined with --username or --shortcode")
        return _service_result(False, messages=messages)

    state = ImportedState.load(config.imported_state)
    eagle = EagleClient(config.eagle_api_base)
    resolved_folder_id = resolve_optional_folder_id(
        folder_id=folder_id,
        folder_path=folder_path,
        eagle=eagle,
        log=logger,
    )
    if resolved_folder_id is False:
        return _service_result(False, messages=messages)

    result = verify_import_records(
        eagle=eagle,
        state=state,
        unique_key=unique_key,
        shortcode=shortcode,
        username=username,
        folder_id=resolved_folder_id,
        dry_run=dry_run,
        log=logger,
    )
    return _service_result(
        True,
        messages=messages,
        checked=result.checked,
        alive=result.alive,
        missing=result.missing,
        alive_but_not_in_folder=result.alive_but_not_in_folder,
        unknown=result.unknown,
        removed=result.removed,
    )


def forget_import(
    config: AppConfig,
    *,
    unique_key: str | None = None,
    shortcode: str | None = None,
    username: str | None = None,
    dry_run: bool = False,
    log: LogFn | None = None,
) -> dict[str, Any]:
    messages: list[str] = []
    logger = _logger(messages, log)
    if not unique_key and not shortcode:
        logger("forget-import requires --unique-key or --shortcode")
        return _service_result(False, messages=messages)
    if unique_key and (shortcode or username):
        logger("forget-import --unique-key cannot be combined with --username or --shortcode")
        return _service_result(False, messages=messages)
    if username and not shortcode:
        logger("forget-import --username requires --shortcode")
        return _service_result(False, messages=messages)

    state = ImportedState.load(config.imported_state)
    result = state.forget(unique_key=unique_key, shortcode=shortcode, username=username, dry_run=dry_run)
    logger(f"matched count: {result.matched_count}")
    logger(f"removed count: {result.removed_count}")
    logger("removed keys:")
    for key in result.removed_keys:
        logger(f"  {key}")
    if result.backup_path is not None:
        logger(f"backup: {result.backup_path}")
    if result.matched_count == 0:
        logger("No imported records matched the given selector.")

    return _service_result(
        True,
        messages=messages,
        matched_count=result.matched_count,
        removed_count=result.removed_count,
        removed_keys=result.removed_keys,
        backup_path=str(result.backup_path) if result.backup_path is not None else None,
    )


def list_folders(config: AppConfig) -> dict[str, Any]:
    try:
        folders = EagleClient(config.eagle_api_base).list_folders()
    except Exception as exc:  # noqa: BLE001 - service result should be GUI-friendly.
        return _service_result(False, messages=[f"error: {exc}"])
    return _service_result(True, folders=folders, total=len(folders), messages=[])


def ensure_folder(config: AppConfig, folder_path: str) -> dict[str, Any]:
    try:
        folder_id = EagleClient(config.eagle_api_base).ensure_folder_path(folder_path)
    except Exception as exc:  # noqa: BLE001 - service result should be GUI-friendly.
        return _service_result(False, messages=[f"error: {exc}"])
    return _service_result(True, folder_id=folder_id, messages=[f"folder id: {folder_id}"])


def resolve_target_folder_id(
    *,
    folder_id: str | None,
    folder_path: str | None,
    eagle: EagleClient,
    dry_run: bool,
    log: LogFn,
) -> str | None:
    if folder_id and folder_path:
        log("error: --folder-id and --folder-path cannot be used together.")
        return None

    if folder_id:
        return folder_id

    if folder_path:
        if dry_run:
            log(f"dry-run: would ensure Eagle folder path: {folder_path}")
            return f"<folder-path:{folder_path}>"
        try:
            resolved_folder_id = eagle.ensure_folder_path(folder_path)
        except Exception as exc:  # noqa: BLE001 - convert API failures into service errors.
            log(f"error: {exc}")
            return None
        log(f"resolved Eagle folder path '{folder_path}' to folder id: {resolved_folder_id}")
        return resolved_folder_id

    log("error: either --folder-id or --folder-path is required.")
    return None


def resolve_optional_folder_id(
    *,
    folder_id: str | None,
    folder_path: str | None,
    eagle: EagleClient,
    log: LogFn,
) -> str | None | bool:
    if folder_id and folder_path:
        log("error: --folder-id and --folder-path cannot be used together.")
        return False

    if folder_id:
        return folder_id

    if not folder_path:
        return None

    try:
        resolved_folder_id = eagle.ensure_folder_path(folder_path)
    except Exception as exc:  # noqa: BLE001 - convert API failures into service errors.
        log(f"error: {exc}")
        return False
    log(f"resolved Eagle folder path '{folder_path}' to folder id: {resolved_folder_id}")
    return resolved_folder_id


def _import_from_items(
    config: AppConfig,
    items: list[ImportItem],
    *,
    folder_id: str | None,
    folder_path: str | None,
    dry_run: bool,
    force: bool,
    verify_eagle: bool,
    show_annotation: bool,
    messages: list[str],
    log: LogFn,
) -> dict[str, Any]:
    eagle = EagleClient(config.eagle_api_base)
    resolved_folder_id = resolve_target_folder_id(
        folder_id=folder_id,
        folder_path=folder_path,
        eagle=eagle,
        dry_run=dry_run,
        log=log,
    )
    if resolved_folder_id is None:
        return _service_result(False, messages=messages)

    state = ImportedState.load(config.imported_state)
    result = import_staging_items(
        items,
        eagle=eagle,
        state=state,
        folder_id=resolved_folder_id,
        dry_run=dry_run,
        force=force,
        verify_eagle=verify_eagle,
        show_annotation=show_annotation,
        log=log,
    )
    return _import_result_to_service(result, messages)


def _import_result_to_service(result: Any, messages: list[str]) -> dict[str, Any]:
    return _service_result(
        result.failed == 0,
        messages=messages,
        total=result.total,
        skipped=result.skipped,
        imported=result.imported,
        failed=result.failed,
        failures=[
            {"unique_key": failure.unique_key, "title": failure.title, "error": failure.error}
            for failure in result.failures
        ],
    )


def _fail_if_no_downloaded_items(
    items: list[ImportItem],
    target_dir: Path,
    *,
    dry_run: bool,
    download_ran: bool,
    messages: list[str],
    log: LogFn,
) -> dict[str, Any] | None:
    if dry_run or not download_ran or items:
        return None

    log(
        "error: gallery-dl completed successfully, but no importable Instagram files "
        f"or metadata were found in {target_dir}. Check the selected date range, "
        "download archive, cookies/login status, and whether the author has posts in that range."
    )
    return _service_result(
        False,
        messages=messages,
        total=0,
        skipped=0,
        imported=0,
        failed=1,
        failures=[],
    )


def _item_summary(item: ImportItem) -> dict[str, Any]:
    return {
        "file_path": str(item.file_path),
        "title": item.title,
        "website": item.website,
        "tags": item.tags,
        "unique_key": item.unique_key,
    }


def _logger(messages: list[str], log: LogFn | None) -> LogFn:
    def emit(message: str) -> None:
        text = str(message)
        messages.append(text)
        if log is not None:
            log(text)

    return emit


def _service_result(ok: bool, *, messages: list[str], **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": ok, "messages": messages}
    result.update(extra)
    return result
