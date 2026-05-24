from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .eagle_client import EagleClient
from .gallerydl_runner import build_gallery_dl_request, run_gallery_dl
from .importer import import_staging_items, verify_import_records
from .metadata_parser import scan_staging_dir
from .state_store import ImportedState
from .utils import detect_instagram_url


DEFAULT_CONFIG_PATH = "config.json"
EXAMPLE_CONFIG_PATH = "config.example.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ins-eagle-sync")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to config JSON.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    detect_parser = subparsers.add_parser("detect", help="Detect Instagram URL mode.")
    detect_parser.add_argument("url")

    run_parser = subparsers.add_parser("run", help="Run gallery-dl for an author, post, or reel URL.")
    run_parser.add_argument("url")
    run_parser.add_argument("--dry-run", action="store_true", help="Print the gallery-dl command without running it.")

    parse_staging_parser = subparsers.add_parser("parse-staging", help="Parse staged media and metadata.")
    parse_staging_parser.add_argument("staging_dir")

    import_staging_parser = subparsers.add_parser("import-staging", help="Import staged media into Eagle.")
    import_staging_parser.add_argument("staging_dir")
    import_staging_parser.add_argument("--folder-id")
    import_staging_parser.add_argument("--folder-path")
    import_staging_parser.add_argument("--dry-run", action="store_true")
    import_staging_parser.add_argument("--force", action="store_true")
    import_staging_parser.add_argument("--verify-eagle", action="store_true")
    import_staging_parser.add_argument("--show-annotation", action="store_true")

    sync_post_parser = subparsers.add_parser("sync-post", help="Download and import a single Instagram post.")
    sync_post_parser.add_argument("post_url")
    sync_post_parser.add_argument("--folder-id")
    sync_post_parser.add_argument("--folder-path")
    sync_post_parser.add_argument("--dry-run", action="store_true")
    sync_post_parser.add_argument("--force", action="store_true")
    sync_post_parser.add_argument("--verify-eagle", action="store_true")
    sync_post_parser.add_argument("--show-annotation", action="store_true")
    sync_post_parser.add_argument("--ignore-archive", action="store_true")
    sync_post_parser.add_argument("--verbose-gallery-dl", action="store_true")

    sync_author_parser = subparsers.add_parser("sync-author", help="Download and import an Instagram author.")
    sync_author_parser.add_argument("author_url")
    sync_author_parser.add_argument("--folder-id")
    sync_author_parser.add_argument("--folder-path")
    sync_author_parser.add_argument("--dry-run", action="store_true")
    sync_author_parser.add_argument("--force", action="store_true")
    sync_author_parser.add_argument("--verify-eagle", action="store_true")
    sync_author_parser.add_argument("--max-posts", type=int)
    sync_author_parser.add_argument("--show-annotation", action="store_true")
    sync_author_parser.add_argument("--ignore-archive", action="store_true")
    sync_author_parser.add_argument("--verbose-gallery-dl", action="store_true")

    forget_import_parser = subparsers.add_parser("forget-import", help="Remove records from imported state.")
    forget_import_parser.add_argument("--unique-key")
    forget_import_parser.add_argument("--username")
    forget_import_parser.add_argument("--shortcode")
    forget_import_parser.add_argument("--dry-run", action="store_true")

    verify_imports_parser = subparsers.add_parser("verify-imports", help="Verify imported Eagle items still exist.")
    verify_imports_parser.add_argument("--unique-key")
    verify_imports_parser.add_argument("--username")
    verify_imports_parser.add_argument("--shortcode")
    verify_imports_parser.add_argument("--folder-id")
    verify_imports_parser.add_argument("--dry-run", action="store_true")

    subparsers.add_parser("list-folders", help="List Eagle folders.")

    ensure_folder_parser = subparsers.add_parser("ensure-folder", help="Create an Eagle folder path if needed.")
    ensure_folder_parser.add_argument("folder_path")

    sync_parser = subparsers.add_parser("sync", help="Author sync mode placeholder.")
    sync_parser.add_argument("url")

    import_parser = subparsers.add_parser("import", help="Single post import mode placeholder.")
    import_parser.add_argument("url")
    import_parser.add_argument("--folder-id", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "detect":
        info = detect_instagram_url(args.url)
        safe_print(
            json.dumps(
                {
                    "mode": info.mode.value,
                    "original_url": info.original_url,
                    "normalized_url": info.normalized_url,
                    "username": info.username,
                    "shortcode": info.shortcode,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "parse-staging":
        config = load_config(resolve_config_path(args.config))
        items = scan_staging_dir(Path(args.staging_dir), title_caption_chars=config.title_caption_chars)
        safe_print(
            json.dumps(
                [
                    {
                        "file_path": str(item.file_path),
                        "title": item.title,
                        "website": item.website,
                        "tags": item.tags,
                        "unique_key": item.unique_key,
                    }
                    for item in items
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    config = load_config(resolve_config_path(args.config))

    if args.command == "list-folders":
        eagle = EagleClient(config.eagle_api_base)
        try:
            folders = eagle.list_folders()
        except Exception as exc:  # noqa: BLE001 - convert API failures into CLI errors.
            safe_print(f"error: {exc}")
            return 1
        safe_print(json.dumps(folders, ensure_ascii=False, indent=2))
        return 0

    if args.command == "ensure-folder":
        eagle = EagleClient(config.eagle_api_base)
        try:
            folder_id = eagle.ensure_folder_path(args.folder_path)
        except Exception as exc:  # noqa: BLE001 - convert API failures into CLI errors.
            safe_print(f"error: {exc}")
            return 1
        safe_print(f"folder id: {folder_id}")
        return 0

    if args.command == "import-staging":
        items = scan_staging_dir(Path(args.staging_dir), title_caption_chars=config.title_caption_chars)
        state = ImportedState.load(config.imported_state)
        eagle = EagleClient(config.eagle_api_base)
        folder_id = resolve_target_folder_id(args, eagle=eagle, dry_run=args.dry_run, log=safe_print)
        if folder_id is None:
            return 1
        result = import_staging_items(
            items,
            eagle=eagle,
            state=state,
            folder_id=folder_id,
            dry_run=args.dry_run,
            force=args.force,
            verify_eagle=args.verify_eagle,
            show_annotation=args.show_annotation,
            log=safe_print,
        )
        return 1 if result.failed else 0

    if args.command == "forget-import":
        if not args.unique_key and not args.shortcode:
            raise SystemExit("forget-import requires --unique-key or --shortcode")
        if args.unique_key and (args.shortcode or args.username):
            raise SystemExit("forget-import --unique-key cannot be combined with --username or --shortcode")
        if args.username and not args.shortcode:
            raise SystemExit("forget-import --username requires --shortcode")

        state = ImportedState.load(config.imported_state)
        result = state.forget(
            unique_key=args.unique_key,
            shortcode=args.shortcode,
            username=args.username,
            dry_run=args.dry_run,
        )
        safe_print(f"matched count: {result.matched_count}")
        safe_print(f"removed count: {result.removed_count}")
        safe_print("removed keys:")
        for key in result.removed_keys:
            safe_print(f"  {key}")
        if result.backup_path is not None:
            safe_print(f"backup: {result.backup_path}")
        if result.matched_count == 0:
            safe_print("No imported records matched the given selector.")
        return 0

    if args.command == "verify-imports":
        if args.unique_key and (args.shortcode or args.username):
            raise SystemExit("verify-imports --unique-key cannot be combined with --username or --shortcode")
        state = ImportedState.load(config.imported_state)
        eagle = EagleClient(config.eagle_api_base)
        verify_import_records(
            eagle=eagle,
            state=state,
            unique_key=args.unique_key,
            shortcode=args.shortcode,
            username=args.username,
            folder_id=args.folder_id,
            dry_run=args.dry_run,
            log=safe_print,
        )
        return 0

    if args.command == "sync-post":
        info = detect_instagram_url(args.post_url)
        if info.mode.value != "post":
            raise SystemExit("sync-post requires a post or reel URL.")

        request = build_gallery_dl_request(
            config,
            info.normalized_url,
            ignore_archive=args.ignore_archive,
            verbose=args.verbose_gallery_dl,
        )
        download_result = run_gallery_dl(
            config,
            info.normalized_url,
            dry_run=args.dry_run,
            ignore_archive=args.ignore_archive,
            verbose=args.verbose_gallery_dl,
            log=safe_print,
        )
        if download_result is not None and download_result.returncode != 0:
            return download_result.returncode

        items = scan_staging_dir(request.target_dir, title_caption_chars=config.title_caption_chars)
        state = ImportedState.load(config.imported_state)
        eagle = EagleClient(config.eagle_api_base)
        folder_id = resolve_target_folder_id(args, eagle=eagle, dry_run=args.dry_run, log=safe_print)
        if folder_id is None:
            return 1
        import_result = import_staging_items(
            items,
            eagle=eagle,
            state=state,
            folder_id=folder_id,
            dry_run=args.dry_run,
            force=args.force,
            verify_eagle=args.verify_eagle,
            show_annotation=args.show_annotation,
            log=safe_print,
        )
        return 1 if import_result.failed else 0

    if args.command == "sync-author":
        info = detect_instagram_url(args.author_url)
        if info.mode.value != "author":
            raise SystemExit("sync-author requires an author URL, e.g. https://www.instagram.com/username/")

        request = build_gallery_dl_request(
            config,
            info.normalized_url,
            ignore_archive=args.ignore_archive,
            verbose=args.verbose_gallery_dl,
            max_posts=args.max_posts,
        )
        download_result = run_gallery_dl(
            config,
            info.normalized_url,
            dry_run=args.dry_run,
            ignore_archive=args.ignore_archive,
            verbose=args.verbose_gallery_dl,
            max_posts=args.max_posts,
            log=safe_print,
        )
        if download_result is not None and download_result.returncode != 0:
            return download_result.returncode

        items = scan_staging_dir(request.target_dir, title_caption_chars=config.title_caption_chars)
        state = ImportedState.load(config.imported_state)
        eagle = EagleClient(config.eagle_api_base)
        folder_id = resolve_target_folder_id(args, eagle=eagle, dry_run=args.dry_run, log=safe_print)
        if folder_id is None:
            return 1
        import_result = import_staging_items(
            items,
            eagle=eagle,
            state=state,
            folder_id=folder_id,
            dry_run=args.dry_run,
            force=args.force,
            verify_eagle=args.verify_eagle,
            show_annotation=args.show_annotation,
            log=safe_print,
        )
        return 1 if import_result.failed else 0

    info = detect_instagram_url(args.url)

    if args.command == "run":
        result = run_gallery_dl(config, info.normalized_url, dry_run=args.dry_run, log=safe_print)
        return 0 if result is None else result.returncode

    if args.command == "sync":
        if info.mode.value != "author":
            raise SystemExit("sync requires an author URL, e.g. https://www.instagram.com/username/")
        safe_print(f"Detected author sync URL: {info.normalized_url}")
        safe_print(f"Staging directory: {config.staging_dir}")
        safe_print("Download/import workflow will be implemented in the next step.")
        return 0

    if args.command == "import":
        if info.mode.value not in {"post", "reel"}:
            raise SystemExit("import requires a post or reel URL.")
        safe_print(f"Detected single post URL: {info.normalized_url}")
        safe_print(f"Target Eagle folder ID: {args.folder_id}")
        safe_print("Download/import workflow will be implemented in the next step.")
        return 0

    raise SystemExit(f"Unknown command: {args.command}")


def resolve_config_path(config_path: str) -> Path:
    path = Path(config_path)
    if path.exists():
        return path

    if config_path == DEFAULT_CONFIG_PATH:
        example_path = Path(EXAMPLE_CONFIG_PATH)
        if example_path.exists():
            return example_path

    return path


def resolve_target_folder_id(
    args: argparse.Namespace,
    *,
    eagle: EagleClient,
    dry_run: bool,
    log=None,
) -> str | None:
    if log is None:
        log = safe_print
    folder_id = getattr(args, "folder_id", None)
    folder_path = getattr(args, "folder_path", None)
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
        except Exception as exc:  # noqa: BLE001 - convert API failures into CLI errors.
            log(f"error: {exc}")
            return None
        log(f"resolved Eagle folder path '{folder_path}' to folder id: {resolved_folder_id}")
        return resolved_folder_id

    log("error: either --folder-id or --folder-path is required.")
    return None


def safe_print(message: object = "") -> None:
    text = str(message)
    encoding = sys.stdout.encoding or "utf-8"
    safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    sys.stdout.write(safe_text + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
