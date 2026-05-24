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


def build_gallery_dl_request(
    config: AppConfig,
    url: str,
    *,
    ignore_archive: bool = False,
    verbose: bool = False,
    max_posts: int | None = None,
) -> GalleryDlRequest:
    info = detect_instagram_url(url)
    target_dir = build_target_dir(config, url)
    return GalleryDlRequest(
        mode=info.mode.value,
        url=info.normalized_url,
        target_dir=target_dir,
        archive_db=config.archive_db,
        command=build_gallery_dl_command(
            config,
            info.normalized_url,
            target_dir,
            ignore_archive=ignore_archive,
            verbose=verbose,
            max_posts=max_posts,
        ),
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


def build_gallery_dl_command(
    config: AppConfig,
    url: str,
    target_dir: Path,
    *,
    ignore_archive: bool = False,
    verbose: bool = False,
    max_posts: int | None = None,
) -> list[str]:
    effective_max_posts = max_posts if max_posts is not None else config.download.max_posts
    command = shlex.split(config.gallery_dl_executable)
    command.append("--config-ignore")
    if verbose:
        command.append("--verbose")
    command.extend(build_cookie_args(config))
    command.append("--write-metadata")
    if not ignore_archive:
        command.extend(["--download-archive", str(config.archive_db)])
    command.extend(
        [
            "--sleep-request",
            config.download.sleep_request,
            "--range",
            f"1-{effective_max_posts}",
            "--directory",
            str(target_dir),
            url,
        ]
    )
    return command


def build_cookie_args(config: AppConfig) -> list[str]:
    if not config.cookies.enabled:
        return []

    if config.cookies.file is not None:
        return ["--cookies", str(config.cookies.file)]

    if config.cookies.from_browser:
        return ["--cookies-from-browser", config.cookies.from_browser]

    raise ValueError("cookies.enabled is true, but no cookies.file or cookies.from_browser is configured")


def run_gallery_dl(
    config: AppConfig,
    url: str,
    *,
    dry_run: bool = False,
    ignore_archive: bool = False,
    verbose: bool = False,
    max_posts: int | None = None,
    log: LogFn = print,
) -> subprocess.CompletedProcess[str] | None:
    request = build_gallery_dl_request(
        config,
        url,
        ignore_archive=ignore_archive,
        verbose=verbose,
        max_posts=max_posts,
    )
    log_gallery_dl_request(request, dry_run=dry_run, log=log)

    missing_cookie_result = validate_cookie_file(config, request, dry_run=dry_run, log=log)
    if missing_cookie_result is not None:
        return missing_cookie_result

    if dry_run:
        return None

    request.target_dir.mkdir(parents=True, exist_ok=True)
    config.archive_db.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        request.command,
        check=False,
        capture_output=True,
        text=True,
        env=build_subprocess_env(config),
    )
    log_gallery_dl_result(result, request.target_dir, log=log)
    return result


def validate_cookie_file(
    config: AppConfig,
    request: GalleryDlRequest,
    *,
    dry_run: bool,
    log: LogFn,
) -> subprocess.CompletedProcess[str] | None:
    if not config.cookies.enabled or config.cookies.file is None or config.cookies.file.exists():
        return None

    message = (
        f"cookies.file does not exist: {config.cookies.file}. "
        "Export Instagram cookies as a Netscape cookies.txt file to this path, "
        "or update cookies.file in the project config.json."
    )
    if dry_run:
        log(f"warning: {message}")
        return None

    log(f"error: {message}")
    return subprocess.CompletedProcess(
        args=request.command,
        returncode=2,
        stdout="",
        stderr=message,
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


def log_gallery_dl_result(
    result: subprocess.CompletedProcess[str],
    target_dir: Path,
    *,
    log: LogFn = print,
) -> None:
    log(f"gallery-dl exit code: {result.returncode}")

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if stdout:
        log("gallery-dl stdout:")
        log(stdout)
    if stderr:
        log("gallery-dl stderr:")
        log(stderr)
        if is_browser_cookie_error(stderr):
            log(
                "hint: gallery-dl could not use browser cookies. Chrome may have locked "
                "or encrypted them in a way this Python process cannot read. Export "
                "Instagram cookies to a Netscape cookies.txt file and set cookies.file "
                "in the project config.json."
            )
        if is_instagram_login_redirect(stderr):
            log(
                "hint: Instagram redirected gallery-dl to the login page. "
                "Create a project config.json from config.example.json and enable cookies "
                "with cookies.from_browser or cookies.file. This tool runs gallery-dl with "
                "--config-ignore, so user-level gallery-dl config files are not loaded."
            )

    metadata_files = find_metadata_files(target_dir) if target_dir.exists() else []
    log(f"metadata JSON files found: {len(metadata_files)}")
    if result.returncode == 0 and not metadata_files:
        log("warning: gallery-dl completed but no metadata JSON files were found in the staging directory.")


def is_instagram_login_redirect(stderr: str) -> bool:
    text = stderr.lower()
    return "instagram" in text and "accounts/login" in text


def is_browser_cookie_error(stderr: str) -> bool:
    text = stderr.lower()
    return (
        "cookies:" in text
        and (
            "permission denied" in text
            or "failed to decrypt cookie" in text
            or "dpapi" in text
            or "nonetype" in text
        )
    )


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
