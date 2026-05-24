from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProxyConfig:
    enabled: bool
    http_proxy: str | None = None
    https_proxy: str | None = None


@dataclass(frozen=True)
class DownloadConfig:
    sleep_request: str = "8-15"
    max_posts: int = 50


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


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return parse_config(data)


def parse_config(data: dict[str, Any]) -> AppConfig:
    proxy_data = data.get("proxy", {})
    download_data = data.get("download", {})

    return AppConfig(
        gallery_dl_executable=str(data["gallery_dl_executable"]),
        staging_dir=Path(data["staging_dir"]).expanduser(),
        archive_db=Path(data["archive_db"]).expanduser(),
        imported_state=Path(data["imported_state"]).expanduser(),
        eagle_api_base=str(data["eagle_api_base"]).rstrip("/"),
        default_eagle_root_folder=str(data["default_eagle_root_folder"]),
        title_caption_chars=int(data.get("title_caption_chars", 20)),
        proxy=ProxyConfig(
            enabled=bool(proxy_data.get("enabled", False)),
            http_proxy=proxy_data.get("http_proxy"),
            https_proxy=proxy_data.get("https_proxy"),
        ),
        download=DownloadConfig(
            sleep_request=str(download_data.get("sleep_request", "8-15")),
            max_posts=int(download_data.get("max_posts", 50)),
        ),
    )
