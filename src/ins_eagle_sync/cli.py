from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .gallerydl_runner import run_gallery_dl
from . import services
from .utils import detect_instagram_url


DEFAULT_CONFIG_PATH = "config.json"
EXAMPLE_CONFIG_PATH = "config.example.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ins-eagle-sync")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to config JSON.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    detect_parser = subparsers.add_parser("detect", help="Detect Instagram URL mode.")
    detect_parser.add_argument("url")

    subparsers.add_parser("gui", help="Open the graphical interface.")

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
    sync_post_parser.add_argument("post_urls", nargs="+")
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
    sync_author_parser.add_argument("--date-from", help="Process author posts created after this ISO date/datetime.")
    sync_author_parser.add_argument("--date-to", help="Process author posts created before this ISO date/datetime.")
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
    verify_imports_parser.add_argument("--folder-path")
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

    if args.command == "gui":
        from .gui import main as gui_main

        gui_main()
        return 0

    if args.command == "parse-staging":
        config = load_config(resolve_config_path(args.config))
        result = services.parse_staging(config, args.staging_dir)
        safe_print(
            json.dumps(
                result["items"],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    config = load_config(resolve_config_path(args.config))

    if args.command == "list-folders":
        result = services.list_folders(config)
        if not result["ok"]:
            _print_messages(result)
            return 1
        safe_print(json.dumps(result["folders"], ensure_ascii=False, indent=2))
        return 0

    if args.command == "ensure-folder":
        result = services.ensure_folder(config, args.folder_path)
        _print_messages(result)
        if not result["ok"]:
            return 1
        return 0

    if args.command == "import-staging":
        result = services.import_staging(
            config,
            args.staging_dir,
            folder_id=args.folder_id,
            folder_path=args.folder_path,
            dry_run=args.dry_run,
            force=args.force,
            verify_eagle=args.verify_eagle,
            show_annotation=args.show_annotation,
            log=safe_print,
        )
        return 0 if result["ok"] else 1

    if args.command == "forget-import":
        result = services.forget_import(
            config,
            unique_key=args.unique_key,
            shortcode=args.shortcode,
            username=args.username,
            dry_run=args.dry_run,
            log=safe_print,
        )
        return 0 if result["ok"] else 1

    if args.command == "verify-imports":
        result = services.verify_imports(
            config,
            unique_key=args.unique_key,
            shortcode=args.shortcode,
            username=args.username,
            folder_id=args.folder_id,
            folder_path=args.folder_path,
            dry_run=args.dry_run,
            log=safe_print,
        )
        return 0 if result["ok"] else 1

    if args.command == "sync-post":
        result = services.sync_posts(
            config,
            " ".join(args.post_urls),
            folder_id=args.folder_id,
            folder_path=args.folder_path,
            dry_run=args.dry_run,
            force=args.force,
            verify_eagle=args.verify_eagle,
            show_annotation=args.show_annotation,
            ignore_archive=args.ignore_archive,
            verbose_gallery_dl=args.verbose_gallery_dl,
            log=safe_print,
        )
        return result.get("returncode", 0 if result["ok"] else 1)

    if args.command == "sync-author":
        info = detect_instagram_url(args.author_url)
        result = services.sync_author(
            config,
            info.normalized_url,
            folder_id=args.folder_id,
            folder_path=args.folder_path,
            dry_run=args.dry_run,
            force=args.force,
            verify_eagle=args.verify_eagle,
            max_posts=args.max_posts,
            date_from=args.date_from,
            date_to=args.date_to,
            show_annotation=args.show_annotation,
            ignore_archive=args.ignore_archive,
            verbose_gallery_dl=args.verbose_gallery_dl,
            log=safe_print,
        )
        return result.get("returncode", 0 if result["ok"] else 1)

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


def safe_print(message: object = "") -> None:
    text = str(message)
    encoding = sys.stdout.encoding or "utf-8"
    safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    sys.stdout.write(safe_text + "\n")


def _print_messages(result: dict[str, object]) -> None:
    for message in result.get("messages", []):
        safe_print(message)


if __name__ == "__main__":
    raise SystemExit(main())
