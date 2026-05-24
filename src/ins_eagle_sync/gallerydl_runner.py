from __future__ import annotations

import shlex
import os
import subprocess
from pathlib import Path

from .config import AppConfig


def build_gallery_dl_command(config: AppConfig, url: str) -> list[str]:
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
            str(config.staging_dir),
            url,
        ]
    )
    return command


def run_gallery_dl(config: AppConfig, url: str) -> subprocess.CompletedProcess[str]:
    config.staging_dir.mkdir(parents=True, exist_ok=True)
    config.archive_db.parent.mkdir(parents=True, exist_ok=True)

    env = None
    if config.proxy.enabled:
        env = os.environ.copy()
        env["HTTP_PROXY"] = config.proxy.http_proxy or ""
        env["HTTPS_PROXY"] = config.proxy.https_proxy or ""

    return subprocess.run(
        build_gallery_dl_command(config, url),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def find_metadata_files(staging_dir: Path) -> list[Path]:
    return sorted(staging_dir.rglob("*.json"))
