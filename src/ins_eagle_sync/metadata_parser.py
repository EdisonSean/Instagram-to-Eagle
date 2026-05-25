from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .utils import InstagramMode, detect_instagram_url, extract_hashtags, normalize_instagram_url


MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov"}
DEFAULT_TITLE_CAPTION_CHARS = 70


@dataclass(frozen=True)
class ImportItem:
    file_path: Path
    title: str
    website: str
    annotation: str
    tags: list[str]
    unique_key: str
    username: str
    shortcode: str
    media_index: int
    caption: str = ""
    date: str | None = None
    source_url: str = ""
    hashtags: list[str] | None = None
    metadata_path: Path | None = None

    @property
    def author(self) -> str:
        return self.username

    @property
    def local_file(self) -> Path:
        return self.file_path


MediaMetadata = ImportItem


def scan_staging_dir(
    staging_dir: str | Path,
    *,
    title_caption_chars: int = DEFAULT_TITLE_CAPTION_CHARS,
) -> list[ImportItem]:
    root = Path(staging_dir)
    media_files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS
    )

    items: list[ImportItem] = []
    for default_index, file_path in enumerate(media_files, start=1):
        metadata_path = find_metadata_json(file_path)
        metadata = _load_single_metadata(metadata_path) if metadata_path else {}
        items.append(
            parse_metadata_item(
                metadata,
                metadata_path,
                file_path=file_path,
                staging_dir=root,
                default_media_index=default_index,
                title_caption_chars=title_caption_chars,
            )
        )
    return sort_import_items(items)


def sort_import_items(items: list[ImportItem]) -> list[ImportItem]:
    return sorted(
        items,
        key=lambda item: (
            item.shortcode,
            item.media_index,
            str(item.file_path).lower(),
        ),
    )


def find_metadata_json(file_path: str | Path) -> Path | None:
    media_path = Path(file_path)
    candidates = [
        Path(str(media_path) + ".json"),
        media_path.with_suffix(".json"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def load_metadata_file(
    path: str | Path,
    *,
    title_caption_chars: int = DEFAULT_TITLE_CAPTION_CHARS,
) -> list[ImportItem]:
    metadata_path = Path(path)
    raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else [raw]
    return [
        parse_metadata_item(
            item,
            metadata_path,
            default_media_index=index,
            title_caption_chars=title_caption_chars,
        )
        for index, item in enumerate(items, start=1)
    ]


def parse_metadata_item(
    item: dict[str, Any],
    metadata_path: Path | None = None,
    *,
    file_path: str | Path | None = None,
    staging_dir: str | Path | None = None,
    default_media_index: int = 1,
    title_caption_chars: int = DEFAULT_TITLE_CAPTION_CHARS,
) -> ImportItem:
    metadata_path = Path(metadata_path) if metadata_path is not None else None
    resolved_file_path = _resolve_file_path(item, metadata_path, file_path)
    root = Path(staging_dir) if staging_dir is not None else None

    source_url_raw = _first_text(item, "post_url", "webpage_url", "source_url", "url")
    normalized_source_url = _normalize_source_url(source_url_raw)
    source_url_info = _detect_source_post_url(normalized_source_url)

    shortcode = _first_text(item, "post_shortcode", "shortcode_id", "shortcode", "sidecar_shortcode", "code")
    if not shortcode:
        shortcode = source_url_info.shortcode if source_url_info is not None else ""
    if not shortcode:
        shortcode = _infer_shortcode_from_path(resolved_file_path, metadata_path, root)
    shortcode = shortcode or "unknown"

    username = _first_text(item, "username", "owner_username", "user", "profile")
    if not username:
        username = _infer_username_from_path(resolved_file_path, root)
    username = username or "unknown"

    caption = _first_text(item, "description", "caption", "title", "content")
    date = _first_text(item, "date", "date_utc", "datetime", "post_date", "created_time", "taken_at") or None
    media_index = (
        _first_int(item, "num", "index", "media_index")
        or _infer_media_index_from_path(resolved_file_path, metadata_path)
        or default_media_index
    )

    website = _website_from_source_url(normalized_source_url, shortcode)
    source_url = normalized_source_url or website
    hashtags = extract_hashtags(caption)
    title = build_import_title(caption, username, title_caption_chars)

    return ImportItem(
        file_path=resolved_file_path,
        title=title,
        website=website,
        annotation=build_annotation(
            username=username,
            date=date,
            shortcode=shortcode,
            media_index=media_index,
            source_url=source_url,
            caption=caption,
        ),
        tags=build_tags(username, shortcode, hashtags),
        unique_key=build_unique_key(username, shortcode, media_index),
        username=username,
        shortcode=shortcode,
        media_index=media_index,
        caption=caption,
        date=date,
        source_url=source_url,
        hashtags=hashtags,
        metadata_path=metadata_path,
    )


def build_import_title(
    caption: str,
    username: str,
    caption_chars: int = DEFAULT_TITLE_CAPTION_CHARS,
) -> str:
    prefix = _visible_prefix(caption, caption_chars)
    if prefix:
        return prefix
    if username and username.lower() != "unknown":
        return username
    return "Instagram Post"


def build_annotation(
    *,
    username: str,
    date: str | None,
    shortcode: str,
    media_index: int,
    source_url: str,
    caption: str,
) -> str:
    return "\n".join(
        [
            f"作者: {username}",
            f"日期: {date or ''}",
            f"Shortcode: {shortcode}",
            f"序号: {media_index:02d}",
            f"来源 URL: {source_url}",
            "Caption 全文:",
            caption,
        ]
    ).strip()


def build_tags(username: str, shortcode: str, hashtags: list[str]) -> list[str]:
    tags = ["instagram", f"author:{username}"]
    for hashtag in hashtags:
        if hashtag not in tags:
            tags.append(hashtag)
    return tags


def build_unique_key(username: str, shortcode: str, media_index: int) -> str:
    return f"instagram:{username}:{shortcode}:{media_index:02d}"


def _normalize_source_url(source_url: str) -> str:
    if not source_url:
        return ""
    try:
        return normalize_instagram_url(source_url)
    except ValueError:
        return source_url.strip()


def _detect_source_post_url(source_url: str) -> Any | None:
    if not source_url:
        return None
    try:
        info = detect_instagram_url(source_url)
    except ValueError:
        return None
    return info if info.mode == InstagramMode.POST else None


def _website_from_source_url(source_url: str, shortcode: str) -> str:
    info = _detect_source_post_url(source_url)
    if info is not None and info.shortcode == shortcode:
        return info.normalized_url
    return f"https://www.instagram.com/p/{shortcode}/"


def _load_single_metadata(metadata_path: Path) -> dict[str, Any]:
    raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        first = raw[0] if raw else {}
        return first if isinstance(first, dict) else {}
    return raw if isinstance(raw, dict) else {}


def _resolve_file_path(
    item: dict[str, Any],
    metadata_path: Path | None,
    file_path: str | Path | None,
) -> Path:
    if file_path is not None:
        return Path(file_path)

    if metadata_path is not None and metadata_path.suffix.lower() == ".json":
        candidate = metadata_path.with_suffix("")
        if candidate.suffix.lower() in MEDIA_EXTENSIONS:
            return candidate

    for key in ("_filename", "filename", "file", "path"):
        value = item.get(key)
        if value:
            path = Path(str(value))
            if path.is_absolute() or metadata_path is None:
                return path
            return metadata_path.parent / path

    if metadata_path is not None:
        return metadata_path.with_suffix("")

    return Path("")


def _first_text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key not in item:
            continue
        text = _value_to_text(item[key])
        if text:
            return text
    return ""


def _value_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("username", "owner_username", "name", "id", "shortcode", "code"):
            text = _value_to_text(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, list):
        for item in value:
            text = _value_to_text(item)
            if text:
                return text
        return ""
    return str(value).strip()


def _first_int(item: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _infer_username_from_path(file_path: Path, staging_dir: Path | None) -> str:
    if staging_dir is None:
        return ""
    try:
        relative = file_path.relative_to(staging_dir)
    except ValueError:
        return ""
    if len(relative.parts) < 2:
        return ""
    username = relative.parts[0]
    return "" if username.lower() == "unknown" else username


def _infer_shortcode_from_path(
    file_path: Path,
    metadata_path: Path | None,
    staging_dir: Path | None,
) -> str:
    path = file_path if str(file_path) else metadata_path
    if path is None:
        return ""

    parent_name = path.parent.name
    if parent_name and parent_name.lower() != "unknown":
        if staging_dir is None or path.parent != staging_dir:
            return parent_name

    for text in (path.stem, path.parent.name):
        match = re.search(r"(?:^|[_\-.])([A-Za-z0-9_-]{5,})(?:$|[_\-.])", text)
        if match:
            return match.group(1)
    return ""


def _infer_media_index_from_path(file_path: Path, metadata_path: Path | None) -> int | None:
    path = file_path if str(file_path) else metadata_path
    if path is None:
        return None

    for text in (path.stem, path.parent.name):
        index = _parse_index_text(text)
        if index is not None:
            return index
    return None


def _parse_index_text(text: str) -> int | None:
    patterns = [
        r"(?:^|[_\-. ])(?:media|image|photo|video|item)?0*([1-9]\d?)(?:$|[_\-. ])",
        r"\(([1-9]\d?)\)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _visible_prefix(value: str, max_chars: int) -> str:
    return " ".join(value.split())[:max_chars].strip()
