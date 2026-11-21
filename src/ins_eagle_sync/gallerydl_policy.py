from __future__ import annotations

import os
import random
import re
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator
from unittest.mock import patch
from urllib.parse import urlsplit

from .runtime import get_user_data_dir


AUTHOR_PAGE_LIMIT = 10
LOGIN_PAGE_LIMIT = 1
RESTRICTED_EXIT_CODE = 75
BUSY_EXIT_CODE = 76
POLICY_ERROR_EXIT_CODE = 77
FEED_PATH = re.compile(r"/api/v1/feed/user/[^/]+/?")
VERIFICATION_PATH = re.compile(r"^/(?:challenge|checkpoint|accounts/login)(?:/|$)")
RESTRICTION_REASONS = {"challenge_required", "checkpoint_required", "feedback_required", "login_required"}


def parse_request_interval(value: str) -> tuple[float, float]:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)(?:\s*-\s*(\d+(?:\.\d+)?))?\s*", value)
    if match is None:
        raise ValueError("Request interval must be a positive number or range in seconds, e.g. 8-15.")
    minimum = float(match[1])
    maximum = float(match[2] or match[1])
    if not 0 < minimum <= maximum < float("inf"):
        raise ValueError("Request interval must be positive and the lower bound must come first.")
    return minimum, maximum


@contextmanager
def request_clock(path: Path) -> Iterator[BinaryIO]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "r+b") as clock:
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(clock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(clock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RequestClockBusy from exc
        yield clock


class RequestClockBusy(Exception):
    pass


class InstagramRestricted(SystemExit):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(RESTRICTED_EXIT_CODE)


class InstagramRequestPolicy:
    def __init__(self, clock: BinaryIO, interval: tuple[float, float], page_limit: int):
        self.clock = clock
        self.interval = interval
        self.page_limit = page_limit
        self.pages = 0

    def before_request(self, url: str) -> None:
        from gallery_dl.exception import StopExtraction

        target = urlsplit(url)
        if _is_instagram(target.hostname) and VERIFICATION_PATH.match(target.path):
            raise InstagramRestricted("Instagram requested login or security verification")
        if _is_instagram(target.hostname) and FEED_PATH.fullmatch(target.path):
            if self.pages >= self.page_limit:
                print(f"Instagram author page limit reached ({self.page_limit} pages).", flush=True)
                raise StopExtraction()
            self.pages += 1

        # Offset zero is reserved for the Windows lock. Use a monotonic time shared by processes.
        self.clock.seek(1)
        try:
            previous = float(self.clock.read(64))
        except ValueError:
            previous = 0.0
        now = time.monotonic()
        if 0 < previous <= now:
            remaining = random.uniform(*self.interval) - (now - previous)
            if remaining > 0:
                time.sleep(remaining)
        self.clock.seek(1)
        self.clock.write(f"{time.monotonic():.9f}\n".encode("ascii"))
        self.clock.truncate()
        self.clock.flush()

    def check_response(self, response) -> None:
        status = response.status_code
        if status == 429:
            raise InstagramRestricted("HTTP 429 Too Many Requests")
        if not _is_instagram(urlsplit(response.url).hostname):
            return
        if status in (401, 403):
            raise InstagramRestricted(f"Instagram denied access (HTTP {status})")
        location = response.headers.get("Location")
        if response.is_redirect and location and VERIFICATION_PATH.match(urlsplit(location).path):
            raise InstagramRestricted("Instagram redirected to login or security verification")
        if "json" in response.headers.get("Content-Type", "").lower():
            try:
                data = response.json()
            except ValueError:
                return
            if isinstance(data, dict):
                for key in ("message", "error_type"):
                    reason = str(data.get(key, "")).lower()
                    if reason in RESTRICTION_REASONS:
                        raise InstagramRestricted(reason)
                if data.get("challenge") or data.get("checkpoint_url"):
                    raise InstagramRestricted("Instagram requested security verification")


def _is_instagram(hostname: str | None) -> bool:
    return bool(hostname and (hostname == "instagram.com" or hostname.endswith(".instagram.com")))


def _restore_windows_child_streams() -> None:
    if os.name != "nt" or (sys.stdout is not None and sys.stderr is not None):
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes

    get_handle = ctypes.WinDLL("kernel32").GetStdHandle
    get_handle.argtypes = [wintypes.DWORD]
    get_handle.restype = wintypes.HANDLE
    for name, identifier in (("stdout", -11), ("stderr", -12)):
        if getattr(sys, name) is None:
            handle = get_handle(identifier)
            if handle not in (None, 0, ctypes.c_void_p(-1).value):
                fd = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
                setattr(sys, name, os.fdopen(fd, "w", buffering=1, encoding="utf-8"))


def _protect_yt_dlp(stack: ExitStack, policy: InstagramRequestPolicy) -> None:
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.networking.exceptions import HTTPError
    except ImportError:
        return

    original_urlopen = YoutubeDL.urlopen

    def urlopen(downloader, request):
        url = request if isinstance(request, str) else (getattr(request, "url", None) or request.full_url)
        policy.before_request(url)
        try:
            return original_urlopen(downloader, request)
        except HTTPError as exc:
            if exc.status == 429:
                exc.response.close()
                raise InstagramRestricted("HTTP 429 Too Many Requests") from exc
            raise

    stack.enter_context(patch.object(YoutubeDL, "urlopen", urlopen))


def main() -> int:
    _restore_windows_child_streams()
    try:
        from gallery_dl import main as gallery_dl_main
        from gallery_dl.extractor.common import RequestsAdapter

        if sys.argv[1:] == ["--version"]:
            return gallery_dl_main()
        interval = parse_request_interval(sys.argv.pop(1))
        page_limit = LOGIN_PAGE_LIMIT if "--simulate" in sys.argv else AUTHOR_PAGE_LIMIT
        with request_clock(get_user_data_dir() / "instagram-request-clock") as clock:
            policy = InstagramRequestPolicy(clock, interval, page_limit)
            adapter_send = RequestsAdapter.send

            def send(adapter, request, **kwargs):
                policy.before_request(request.url)
                response = adapter_send(adapter, request, **kwargs)
                try:
                    policy.check_response(response)
                except InstagramRestricted:
                    response.close()
                    raise
                return response

            with ExitStack() as stack:
                stack.enter_context(patch.object(RequestsAdapter, "send", send))
                _protect_yt_dlp(stack, policy)
                return gallery_dl_main()
    except InstagramRestricted as exc:
        print(f"Instagram request stopped: {exc.reason}", file=sys.stderr, flush=True)
        return RESTRICTED_EXIT_CODE
    except RequestClockBusy:
        print("An Instagram task is already running. This task did not start.", file=sys.stderr, flush=True)
        return BUSY_EXIT_CODE
    except (ImportError, IndexError, OSError, ValueError) as exc:
        print(f"Could not start Instagram request protection: {exc}", file=sys.stderr, flush=True)
        return POLICY_ERROR_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
