from __future__ import annotations

import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable

from .config import AppConfig, resolve_gallery_dl_command, resolve_ytdlp_command
from .proxy_utils import build_proxy_env
from .utils import InstagramMode, detect_instagram_url


LogFn = Callable[[str], None]
NO_OUTPUT_STILL_RUNNING_SECONDS = 60.0
NO_OUTPUT_STUCK_SECONDS = 120.0
NO_OUTPUT_POLL_SECONDS = 0.2
DATE_FILTER_FALLBACK_MAX_POSTS = 500
DATE_FILTER_FALLBACK_TERMINATE_SKIPS = 20
CDN_TIMEOUT_HINT = "Instagram CDN 下载超时，gallery-dl 正在重试，可能与网络或代理有关。"
STILL_RUNNING_HINT = "下载仍在进行。"
POSSIBLY_STUCK_HINT = "可能卡住。"
DATE_FILTER_FALLBACK_HINT = (
    "提示：当前 gallery-dl 不支持原生日期停止，将使用时间过滤 + 最近 "
    f"{DATE_FILTER_FALLBACK_MAX_POSTS} 条安全上限，并在连续跳过 "
    f"{DATE_FILTER_FALLBACK_TERMINATE_SKIPS} 个旧文件后停止，避免作者主页翻页卡住。"
)
YTDLP_MISSING_HINT = (
    "提示：未找到 yt-dlp / youtube-dl。gallery-dl 会尝试备用下载方式；"
    "如果视频下载失败，请确认发布包 tools/yt-dlp.exe 存在。"
)


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
    date_from: str | None = None,
    date_to: str | None = None,
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
            date_from=date_from,
            date_to=date_to,
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
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[str]:
    info = detect_instagram_url(url)
    effective_max_posts = max_posts if max_posts is not None else config.download.max_posts
    date_from = _optional_date_filter(date_from, "date_from")
    date_to = _optional_date_filter(date_to, "date_to")
    if info.mode == InstagramMode.AUTHOR and (effective_max_posts == 0 or effective_max_posts < -1):
        raise ValueError("max_posts must be -1 or greater than 0")
    command = resolve_gallery_dl_command(config)
    if not command:
        raise RuntimeError("未找到 gallery-dl，无法下载。请确认发布包完整。")
    command_prefix = tuple(command)
    command.append("--config-ignore")
    if verbose:
        command.append("--verbose")
    command.extend(build_cookie_args(config))
    command.append("--write-metadata")
    if not ignore_archive:
        command.extend(["--download-archive", str(config.archive_db)])
    command.extend(["--sleep-request", config.download.sleep_request])
    range_was_added = False
    if info.mode == InstagramMode.AUTHOR and effective_max_posts != -1:
        command.extend(["--range", f"1-{effective_max_posts}"])
        range_was_added = True
    if info.mode == InstagramMode.AUTHOR:
        if date_from or date_to:
            if gallery_dl_supports_date_options(command_prefix):
                if date_from:
                    command.extend(["--date-after", date_from])
                if date_to:
                    command.extend(["--date-before", date_to])
            else:
                post_filter = build_gallery_dl_date_filter(date_from=date_from, date_to=date_to)
                if post_filter:
                    command.extend(["--post-filter", post_filter])
                    fallback_range_was_added = False
                    if not range_was_added:
                        command.extend(["--range", f"1-{DATE_FILTER_FALLBACK_MAX_POSTS}"])
                        fallback_range_was_added = True
                    if should_terminate_date_filter_fallback(
                        date_from=date_from,
                        fallback_range_was_added=fallback_range_was_added,
                    ):
                        command.extend(["--terminate", str(DATE_FILTER_FALLBACK_TERMINATE_SKIPS)])
    command.extend(["--directory", str(target_dir), url])
    return command


def build_cookie_args(config: AppConfig) -> list[str]:
    if not config.cookies.enabled:
        return []

    if config.cookies.file is not None:
        return ["--cookies", str(config.cookies.file)]

    if config.cookies.from_browser:
        return ["--cookies-from-browser", config.cookies.from_browser]

    raise ValueError("cookies.enabled is true, but no cookies.file or cookies.from_browser is configured")


@lru_cache(maxsize=16)
def gallery_dl_supports_date_options(command_prefix: tuple[str, ...]) -> bool:
    if not command_prefix:
        return False
    try:
        result = subprocess.run(
            [*command_prefix, "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False
    help_text = f"{result.stdout}\n{result.stderr}"
    return "--date-after" in help_text and "--date-before" in help_text


def command_uses_date_filter_fallback(command: list[str]) -> bool:
    return "--post-filter" in command and f"1-{DATE_FILTER_FALLBACK_MAX_POSTS}" in command


def should_terminate_date_filter_fallback(
    *,
    date_from: str | None,
    fallback_range_was_added: bool,
) -> bool:
    return bool(date_from and fallback_range_was_added)


def run_gallery_dl(
    config: AppConfig,
    url: str,
    *,
    dry_run: bool = False,
    ignore_archive: bool = False,
    verbose: bool = False,
    max_posts: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    log: LogFn = print,
) -> subprocess.CompletedProcess[str] | None:
    request = build_gallery_dl_request(
        config,
        url,
        ignore_archive=ignore_archive,
        verbose=verbose,
        max_posts=max_posts,
        date_from=date_from,
        date_to=date_to,
    )
    log_gallery_dl_request(request, dry_run=dry_run, log=log)
    if command_uses_date_filter_fallback(request.command):
        log(DATE_FILTER_FALLBACK_HINT)

    missing_cookie_result = validate_cookie_file(config, request, dry_run=dry_run, log=log)
    if missing_cookie_result is not None:
        return missing_cookie_result

    if dry_run:
        return None

    request.target_dir.mkdir(parents=True, exist_ok=True)
    config.archive_db.parent.mkdir(parents=True, exist_ok=True)

    env = build_subprocess_env(config)
    log_proxy_status(config, env=env, log=log)
    result = run_subprocess_realtime(request.command, env=env, log=log)
    log_gallery_dl_result(result, request.target_dir, log=log, log_captured_output=False)
    return result


def run_subprocess_realtime(
    command: list[str],
    *,
    env: dict[str, str] | None,
    log: LogFn,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        bufsize=1,
    )
    events: queue.Queue[tuple[str, str | None]] = queue.Queue()
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    for stream_name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
        thread = threading.Thread(
            target=_enqueue_stream_lines,
            args=(stream_name, stream, events),
            daemon=True,
        )
        thread.start()

    stream_headers_logged: set[str] = set()
    timeout_hint_logged = False
    ytdlp_hint_logged = False
    still_running_logged = False
    stuck_logged = False
    finished_streams = 0
    last_output_at = time.monotonic()

    while True:
        if process.poll() is not None and finished_streams >= 2 and events.empty():
            break

        try:
            stream_name, line = events.get(timeout=NO_OUTPUT_POLL_SECONDS)
        except queue.Empty:
            if process.poll() is None:
                now = time.monotonic()
                silent_for = now - last_output_at
                if silent_for >= NO_OUTPUT_STUCK_SECONDS and not stuck_logged:
                    log(POSSIBLY_STUCK_HINT)
                    stuck_logged = True
                elif silent_for >= NO_OUTPUT_STILL_RUNNING_SECONDS and not still_running_logged:
                    log(STILL_RUNNING_HINT)
                    still_running_logged = True
            continue

        if line is None:
            finished_streams += 1
            continue

        if stream_name == "stdout":
            stdout_lines.append(line)
        else:
            stderr_lines.append(line)

        text = line.rstrip("\r\n")
        if text:
            if stream_name not in stream_headers_logged:
                log(f"gallery-dl {stream_name}:")
                stream_headers_logged.add(stream_name)
            log(text)
            last_output_at = time.monotonic()
            still_running_logged = False
            stuck_logged = False
            if is_network_timeout_warning(text) and not timeout_hint_logged:
                log(CDN_TIMEOUT_HINT)
                timeout_hint_logged = True
            if is_ytdlp_missing_warning(text) and not ytdlp_hint_logged:
                log(YTDLP_MISSING_HINT)
                ytdlp_hint_logged = True

    returncode = process.wait()
    return subprocess.CompletedProcess(
        args=command,
        returncode=returncode,
        stdout="".join(stdout_lines),
        stderr="".join(stderr_lines),
    )


def _enqueue_stream_lines(
    stream_name: str,
    stream: object,
    events: queue.Queue[tuple[str, str | None]],
) -> None:
    try:
        if stream is not None:
            for line in stream:
                events.put((stream_name, str(line)))
    finally:
        events.put((stream_name, None))


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
    mode = getattr(config.proxy, "mode", "manual" if config.proxy.enabled else "none")
    if mode == "manual" and not config.proxy.http_proxy and not config.proxy.https_proxy:
        env = build_proxy_env(config.proxy)
    elif mode in {"auto", "manual", "none"}:
        env = build_proxy_env(config.proxy)
    elif not config.proxy.enabled:
        env = build_proxy_env(config.proxy)
    else:
        env = build_proxy_env(config.proxy)
    return _add_ytdlp_tools_to_path(env, config)


def log_proxy_status(config: AppConfig, *, env: dict[str, str] | None, log: LogFn) -> None:
    mode = getattr(config.proxy, "mode", "manual" if config.proxy.enabled else "none")
    http_proxy = (env or {}).get("HTTP_PROXY", "")
    https_proxy = (env or {}).get("HTTPS_PROXY", "")
    proxy = http_proxy or https_proxy
    if mode == "auto":
        if proxy:
            log(f"正常：已自动检测到系统代理 {proxy}")
        else:
            log("提示：未检测到系统代理，将直接连接网络。")
    elif mode == "manual":
        if proxy:
            if http_proxy and not config.proxy.https_proxy:
                log("提示：HTTPS 代理为空，已自动使用 HTTP 代理。")
            log(f"正常：正在使用手动代理 {proxy}")
        else:
            log("提示：手动代理未填写，将直接连接网络。")
    else:
        log("提示：当前设置为不使用代理。")


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
    log_captured_output: bool = True,
) -> None:
    log(f"gallery-dl exit code: {result.returncode}")

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if stdout and log_captured_output:
        log("gallery-dl stdout:")
        log(stdout)
    if stderr and log_captured_output:
        log("gallery-dl stderr:")
        log(stderr)
    if stderr:
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
        if is_network_timeout_warning(stderr):
            log(CDN_TIMEOUT_HINT)
        if is_ytdlp_missing_warning(stderr):
            log(YTDLP_MISSING_HINT)

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


def is_network_timeout_warning(text: str) -> bool:
    lowered = text.lower()
    return (
        "read timed out" in lowered
        or "httpsconnectionpool" in lowered
        or ("downloader.http" in lowered and "warning" in lowered)
    )


def is_ytdlp_missing_warning(text: str) -> bool:
    lowered = text.lower()
    return "cannot import yt-dlp or youtube-dl" in lowered


def _add_ytdlp_tools_to_path(env: dict[str, str] | None, config: AppConfig) -> dict[str, str] | None:
    ytdlp_command = resolve_ytdlp_command(config)
    if not ytdlp_command or len(ytdlp_command) != 1:
        return env
    executable = Path(ytdlp_command[0])
    if executable.name.lower() != "yt-dlp.exe" or not executable.exists():
        return env
    updated = dict(env or {})
    current_path = updated.get("PATH", "")
    tool_dir = str(executable.parent)
    updated["PATH"] = f"{tool_dir};{current_path}" if current_path else tool_dir
    return updated


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


def _optional_date_filter(value: str | None, name: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if _is_unix_timestamp(text):
        return text
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO date, ISO datetime, or Unix timestamp") from exc
    return text


def build_gallery_dl_date_filter(*, date_from: str | None, date_to: str | None) -> str | None:
    parts = []
    if date_from:
        parts.append(f"date >= {_datetime_filter_literal(date_from)}")
    if date_to:
        parts.append(f"date < {_datetime_filter_literal(date_to)}")
    if not parts:
        return None
    return "date and " + " and ".join(parts)


def _datetime_filter_literal(value: str) -> str:
    parsed = _parse_filter_datetime(value)
    return (
        "datetime("
        f"{parsed.year}, {parsed.month}, {parsed.day}, "
        f"{parsed.hour}, {parsed.minute}, {parsed.second}"
        ")"
    )


def _parse_filter_datetime(value: str) -> datetime:
    if _is_unix_timestamp(value):
        return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed_date = date.fromisoformat(value)
        return datetime(parsed_date.year, parsed_date.month, parsed_date.day)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def _is_unix_timestamp(value: str) -> bool:
    return value.isdigit()
