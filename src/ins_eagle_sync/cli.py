from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config
from .gallerydl_runner import run_gallery_dl
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
        print(
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

    config = load_config(resolve_config_path(args.config))
    info = detect_instagram_url(args.url)

    if args.command == "run":
        result = run_gallery_dl(config, info.normalized_url, dry_run=args.dry_run)
        return 0 if result is None else result.returncode

    if args.command == "sync":
        if info.mode.value != "author":
            raise SystemExit("sync requires an author URL, e.g. https://www.instagram.com/username/")
        print(f"Detected author sync URL: {info.normalized_url}")
        print(f"Staging directory: {config.staging_dir}")
        print("Download/import workflow will be implemented in the next step.")
        return 0

    if args.command == "import":
        if info.mode.value not in {"post", "reel"}:
            raise SystemExit("import requires a post or reel URL.")
        print(f"Detected single post URL: {info.normalized_url}")
        print(f"Target Eagle folder ID: {args.folder_id}")
        print("Download/import workflow will be implemented in the next step.")
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


if __name__ == "__main__":
    raise SystemExit(main())
