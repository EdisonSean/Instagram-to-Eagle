from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import AppConfig
from .utils import InstagramMode, detect_instagram_url


LogFn = Callable[[str], None]


@dataclass(frozen=True)
class GalleryDlRequest:
    mode: str
    url: str
    target_dir: Path
    archive_db: Path
    command: list[str]


def build_gallery_dl_request(config: AppConfig, url: str) -> GalleryDlRequest:
    info = detect_instagram_url(url)
    target_dir = build_target_dir(config, url)
    return GalleryDlRequest(
        mode=info.mode.value,
        url=info.normalized_url,
        target_dir=target_dir,
        archive_db=config.archive_db,
        command=build_gallery_dl_command(config, info.normalized_url, target_dir),
    )


def build_target_dir(config: AppConfig, url: str) -> Path:
    info = detect_instagram_url(url)
    if info.mode == InstagramMode.AUTHOR:
        if not info.username:
            raise ValueError("Author URL is missing username")
        return config.staging_dir / info.username

    if info.mode == InstagramMode.POST:
        shortcode = info.shortcode or "unknown"
        return config.staging_dir / "unknown" / shortcode

    raise ValueError(f"Unsupported gallery-dl mode: {info.mode.value}")


def build_gallery_dl_command(config: AppConfig, url: str, target_dir: Path) -> list[str]:
    command = shlex.split(config.gallery_dl_executable)
    command.extend(
        [
            "--write-metadata",
            "--download-archive",
            str(config.archive_db),
            "--sleep-request",
            config.download.sleep_request,
            "--range",
            f"1-{config.download.max_posts}",
            "--directory",
            str(target_dir),
            url,
        ]
    )
    return command


def run_gallery_dl(
    config: AppConfig,
    url: str,
    *,
    dry_run: bool = False,
    log: LogFn = print,
) -> subprocess.CompletedProcess[str] | None:
    request = build_gallery_dl_request(config, url)
    log_gallery_dl_request(request, dry_run=dry_run, log=log)

    if dry_run:
        return None

    request.target_dir.mkdir(parents=True, exist_ok=True)
    config.archive_db.parent.mkdir(parents=True, exist_ok=True)

    return subprocess.run(
        request.command,
        check=False,
        capture_output=True,
        text=True,
        env=build_subprocess_env(config),
    )


def build_subprocess_env(config: AppConfig) -> dict[str, str] | None:
    if not config.proxy.enabled:
        return None

    env = os.environ.copy()
    env["HTTP_PROXY"] = config.proxy.http_proxy or ""
    env["HTTPS_PROXY"] = config.proxy.https_proxy or ""
    return env


def log_gallery_dl_request(
    request: GalleryDlRequest,
    *,
    dry_run: bool,
    log: LogFn = print,
) -> None:
    log(f"gallery-dl mode: {request.mode}")
    log(f"target URL: {request.url}")
    log(f"staging directory: {request.target_dir}")
    log(f"archive database: {request.archive_db}")
    log(f"dry run: {dry_run}")
    log(f"command: {format_command_for_log(request.command)}")


def format_command_for_log(command: list[str]) -> str:
    sanitized = sanitize_command_for_log(command)
    return subprocess.list2cmdline(sanitized)


def sanitize_command_for_log(command: list[str]) -> list[str]:
    sanitized: list[str] = []
    hide_next = False

    for part in command:
        lowered = part.lower()
        if hide_next:
            sanitized.append("<hidden>")
            hide_next = False
            continue

        if "cookie" in lowered:
            if "=" in part:
                option, _value = part.split("=", 1)
                sanitized.append(f"{option}=<hidden>")
            else:
                sanitized.append(part)
                hide_next = True
            continue

        sanitized.append(part)

    return sanitized


def find_metadata_files(staging_dir: Path) -> list[Path]:
    return sorted(staging_dir.rglob("*.json"))
