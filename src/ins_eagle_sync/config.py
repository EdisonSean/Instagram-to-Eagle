from __future__ import annotations

import json
import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .runtime import get_app_dir, is_frozen


DEFAULT_GALLERY_DL_EXECUTABLE = "py -m gallery_dl"
DEFAULT_YT_DLP_EXECUTABLE = ""
GALLERY_DL_EXE_NAME = "gallery-dl.exe"
YT_DLP_EXE_NAME = "yt-dlp.exe"
FROZEN_GALLERY_DL_MODULE_ARG = "--ins-eagle-sync-gallery-dl"


@dataclass(frozen=True)
class ProxyConfig:
    enabled: bool
    http_proxy: str | None = None
    https_proxy: str | None = None
    mode: str = "auto"
    detected_proxy: str | None = None


@dataclass(frozen=True)
class DownloadConfig:
    sleep_request: str = "8-15"
    max_posts: int = -1


@dataclass(frozen=True)
class CookiesConfig:
    enabled: bool = False
    from_browser: str | None = None
    file: Path | None = None


@dataclass(frozen=True)
class AppConfig:
    gallery_dl_executable: str
    staging_dir: Path
    archive_db: Path
    imported_state: Path
    eagle_api_base: str
    default_eagle_root_folder: str
    title_caption_chars: int
    proxy: ProxyConfig
    download: DownloadConfig
    cookies: CookiesConfig
    yt_dlp_executable: str | None = None
    default_eagle_folder_path: str = ""
    default_eagle_folder_id: str | None = None
    last_eagle_folder_path: str = ""
    last_eagle_folder_id: str | None = None


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    return parse_config(data)


def parse_config(data: dict[str, Any]) -> AppConfig:
    proxy_data = data.get("proxy", {})
    download_data = data.get("download", {})
    cookies_data = data.get("cookies", {})
    default_folder_path = str(
        data.get("default_eagle_folder_path")
        or data.get("default_eagle_root_folder")
        or ""
    )

    return AppConfig(
        gallery_dl_executable=str(data.get("gallery_dl_executable") or DEFAULT_GALLERY_DL_EXECUTABLE),
        yt_dlp_executable=_optional_text(data.get("yt_dlp_executable")),
        staging_dir=Path(data["staging_dir"]).expanduser(),
        archive_db=Path(data["archive_db"]).expanduser(),
        imported_state=Path(data["imported_state"]).expanduser(),
        eagle_api_base=str(data["eagle_api_base"]).rstrip("/"),
        default_eagle_root_folder=str(data.get("default_eagle_root_folder") or default_folder_path),
        title_caption_chars=int(data.get("title_caption_chars", 70)),
        proxy=ProxyConfig(
            enabled=_proxy_enabled(proxy_data),
            http_proxy=proxy_data.get("http_proxy"),
            https_proxy=proxy_data.get("https_proxy"),
            mode=_proxy_mode(proxy_data),
            detected_proxy=_optional_text(proxy_data.get("detected_proxy")),
        ),
        download=DownloadConfig(
            sleep_request=str(download_data.get("sleep_request", "8-15")),
            max_posts=int(download_data.get("max_posts", -1)),
        ),
        cookies=CookiesConfig(
            enabled=bool(cookies_data.get("enabled", False)),
            from_browser=_optional_text(cookies_data.get("from_browser")),
            file=_optional_path(cookies_data.get("file")),
        ),
        default_eagle_folder_path=default_folder_path,
        default_eagle_folder_id=_optional_text(data.get("default_eagle_folder_id")),
        last_eagle_folder_path=str(data.get("last_eagle_folder_path") or ""),
        last_eagle_folder_id=_optional_text(data.get("last_eagle_folder_id")),
    )


def resolve_gallery_dl_command(config: AppConfig) -> list[str]:
    configured = str(config.gallery_dl_executable or "").strip()
    if configured and not _is_default_gallery_dl_executable(configured):
        return split_command(configured)

    executable = find_gallery_dl_executable()
    if executable is not None:
        return [str(executable)]

    if is_frozen():
        return [sys.executable, FROZEN_GALLERY_DL_MODULE_ARG]

    return split_command(DEFAULT_GALLERY_DL_EXECUTABLE)


def resolve_ytdlp_command(config: AppConfig) -> list[str] | None:
    configured = str(config.yt_dlp_executable or "").strip()
    if configured:
        return split_command(configured)

    executable = find_ytdlp_executable()
    if executable is not None:
        return [str(executable)]

    if is_frozen():
        return None

    return split_command("py -m yt_dlp")


def split_command(command: str) -> list[str]:
    text = str(command or "").strip()
    if not text:
        return []
    if os.name == "nt":
        try:
            import ctypes

            argc = ctypes.c_int()
            ctypes.windll.shell32.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
            ctypes.windll.shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
            argv = ctypes.windll.shell32.CommandLineToArgvW(text, ctypes.byref(argc))
            if argv:
                try:
                    return [argv[index] for index in range(argc.value)]
                finally:
                    ctypes.windll.kernel32.LocalFree(argv)
        except Exception:
            return [part.strip('"') for part in shlex.split(text, posix=False)]
    return shlex.split(text)


def find_gallery_dl_executable() -> Path | None:
    return _find_tool_executable(GALLERY_DL_EXE_NAME)


def find_ytdlp_executable() -> Path | None:
    return _find_tool_executable(YT_DLP_EXE_NAME)


def _find_tool_executable(name: str) -> Path | None:
    for candidate in _tool_candidates(name):
        if candidate.exists():
            return candidate
    return None


def _tool_candidates(name: str) -> list[Path]:
    app_dir = get_app_dir()
    if is_frozen():
        return [
            app_dir / "tools" / name,
            app_dir / name,
        ]
    return [
        app_dir / "tools" / name,
        app_dir / name,
        Path("tools") / name,
        Path(name),
    ]


def _is_default_gallery_dl_executable(value: str) -> bool:
    return " ".join(value.split()) == DEFAULT_GALLERY_DL_EXECUTABLE


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_path(value: Any) -> Path | None:
    text = _optional_text(value)
    if text is None:
        return None
    return Path(text).expanduser()


def _proxy_mode(proxy_data: dict[str, Any]) -> str:
    mode = _optional_text(proxy_data.get("mode"))
    if mode in {"auto", "manual", "none"}:
        return mode
    if proxy_data.get("http_proxy") or proxy_data.get("https_proxy"):
        return "manual"
    if "enabled" in proxy_data:
        return "manual" if bool(proxy_data.get("enabled")) else "none"
    return "auto"


def _proxy_enabled(proxy_data: dict[str, Any]) -> bool:
    return _proxy_mode(proxy_data) != "none"
