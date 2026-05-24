from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse


class InstagramMode(str, Enum):
    AUTHOR = "author"
    POST = "post"
    REEL = "reel"


@dataclass(frozen=True)
class InstagramUrl:
    mode: InstagramMode
    original_url: str
    normalized_url: str
    username: str | None = None
    shortcode: str | None = None


_RESERVED_AUTHOR_PATHS = {
    "accounts",
    "about",
    "api",
    "direct",
    "explore",
    "p",
    "reel",
    "reels",
    "stories",
}

_HASHTAG_RE = re.compile(r"(?<!\w)#([\w\u4e00-\u9fff]+)", re.UNICODE)


def detect_instagram_url(url: str) -> InstagramUrl:
    """Detect the supported Instagram URL mode."""

    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Instagram URL must use http or https")

    host = parsed.netloc.lower()
    if host not in {"instagram.com", "www.instagram.com"}:
        raise ValueError("URL host must be instagram.com")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) == 1:
        username = parts[0]
        if username.lower() in _RESERVED_AUTHOR_PATHS:
            raise ValueError(f"Unsupported Instagram path: {username}")
        return InstagramUrl(
            mode=InstagramMode.AUTHOR,
            original_url=url,
            normalized_url=f"https://www.instagram.com/{username}/",
            username=username,
        )

    if len(parts) >= 2 and parts[0] in {"p", "reel"}:
        shortcode = parts[1]
        return InstagramUrl(
            mode=InstagramMode.POST,
            original_url=url,
            normalized_url=f"https://www.instagram.com/{parts[0]}/{shortcode}/",
            shortcode=shortcode,
        )

    raise ValueError("Unsupported Instagram URL. Use an author, post, or reel URL.")


def extract_hashtags(caption: str | None) -> list[str]:
    if not caption:
        return []

    seen: set[str] = set()
    tags: list[str] = []
    for match in _HASHTAG_RE.findall(caption):
        tag = match.lower()
        if tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return tags


def build_eagle_title(
    caption: str | None,
    shortcode: str,
    media_index: int,
    caption_chars: int = 20,
) -> str:
    caption_head = normalize_whitespace(caption or "")[:caption_chars].strip()
    parts = [part for part in [caption_head, shortcode, str(media_index)] if part]
    return " - ".join(parts)


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())
