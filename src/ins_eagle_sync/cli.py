from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config
from .utils import detect_instagram_url


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ins-eagle-sync")
    parser.add_argument("--config", default="config.json", help="Path to config JSON.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    detect_parser = subparsers.add_parser("detect", help="Detect Instagram URL mode.")
    detect_parser.add_argument("url")

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

    config = load_config(Path(args.config))
    info = detect_instagram_url(args.url)

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


if __name__ == "__main__":
    raise SystemExit(main())
