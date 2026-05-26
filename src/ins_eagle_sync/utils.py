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
    "tv",
}

_HASHTAG_RE = re.compile(r"(?<!\w)#([\w\u4e00-\u9fff]+)", re.UNICODE)
_URL_SEPARATOR_RE = re.compile(r"[\s,，;；]+")
_URL_EDGE_CHARS = "\"'“”‘’()[]{}<>"
_URL_TRAILING_CHARS = ".,，;；。"


def normalize_instagram_url(url: str) -> str:
    """Return the canonical Instagram URL used by downloads and Eagle metadata."""

    return detect_instagram_url(url).normalized_url


def split_instagram_url_text(text: str) -> list[str]:
    """Split user-pasted Instagram URL text into URL-like tokens.

    The GUI accepts the common paste formats users naturally try: one URL per
    line, space-separated URLs, or comma/semicolon-separated URLs.
    """

    urls: list[str] = []
    for raw in _URL_SEPARATOR_RE.split(text.strip()):
        token = raw.strip().strip(_URL_EDGE_CHARS).rstrip(_URL_TRAILING_CHARS)
        if token:
            urls.append(token)
    return urls


def normalize_instagram_post_urls(text: str) -> list[str]:
    """Return de-duplicated canonical post/reel/tv URLs from user text."""

    normalized_urls: list[str] = []
    seen: set[str] = set()
    for raw_url in split_instagram_url_text(text):
        info = detect_instagram_url(raw_url)
        if info.mode != InstagramMode.POST:
            raise ValueError("Single-post mode only supports /p/, /reel/, or /tv/ URLs.")
        if info.normalized_url in seen:
            continue
        normalized_urls.append(info.normalized_url)
        seen.add(info.normalized_url)
    return normalized_urls


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

    if len(parts) >= 2 and parts[0] in {"p", "reel", "tv"}:
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
