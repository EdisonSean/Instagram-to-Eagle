from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .utils import extract_hashtags


@dataclass(frozen=True)
class MediaMetadata:
    shortcode: str
    media_index: int
    source_url: str
    caption: str
    author: str
    date: str | None
    local_file: Path | None
    hashtags: list[str]


def load_metadata_file(path: str | Path) -> list[MediaMetadata]:
    metadata_path = Path(path)
    raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else [raw]
    return [parse_metadata_item(item, metadata_path) for item in items]


def parse_metadata_item(item: dict[str, Any], metadata_path: Path | None = None) -> MediaMetadata:
    shortcode = _first_text(item, "shortcode", "post_shortcode", "code")
    if not shortcode:
        raise ValueError("metadata item is missing shortcode")

    media_index = int(item.get("num") or item.get("media_index") or item.get("index") or 1)
    caption = _first_text(item, "description", "caption", "content")
    author = _first_text(item, "username", "owner_username", "author", "user")
    source_url = _first_text(item, "post_url", "webpage_url", "url")
    date = _first_text(item, "date", "created_time", "taken_at")
    local_file = _guess_local_file(item, metadata_path)

    return MediaMetadata(
        shortcode=shortcode,
        media_index=media_index,
        source_url=source_url or f"https://www.instagram.com/p/{shortcode}/",
        caption=caption,
        author=author,
        date=date or None,
        local_file=local_file,
        hashtags=extract_hashtags(caption),
    )


def _first_text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return str(value)
    return ""


def _guess_local_file(item: dict[str, Any], metadata_path: Path | None) -> Path | None:
    for key in ("_filename", "filename", "file"):
        value = item.get(key)
        if value:
            path = Path(str(value))
            if path.is_absolute() or metadata_path is None:
                return path
            return metadata_path.parent / path
    return None
