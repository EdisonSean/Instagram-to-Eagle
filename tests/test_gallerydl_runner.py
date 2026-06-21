import sys
from io import StringIO
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ins_eagle_sync.config import AppConfig, CookiesConfig, DownloadConfig, ProxyConfig
from ins_eagle_sync.gallerydl_runner import (
    DATE_FILTER_FALLBACK_HINT,
    DATE_FILTER_FALLBACK_MAX_POSTS,
    DATE_FILTER_FALLBACK_TERMINATE_SKIPS,
    GALLERY_DL_CANCELLED_HINT,
    GALLERY_DL_CANCELLED_RETURN_CODE,
    YTDLP_MISSING_HINT,
    build_gallery_dl_date_filter,
    build_gallery_dl_request,
    build_subprocess_env,
    format_command_for_log,
    is_ytdlp_missing_warning,
    run_subprocess_realtime,
    run_gallery_dl,
)


class FakePopen:
    def __init__(self, command, *, stdout_text="", stderr_text="", returncode=0, **kwargs):
        self.command = command
        self.kwargs = kwargs
        self.stdout = StringIO(stdout_text)
        self.stderr = StringIO(stderr_text)
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def wait(self):
        return self.returncode


class SilentFakePopen(FakePopen):
    def __init__(self, command, **kwargs):
        super().__init__(command, stdout_text="", stderr_text="", returncode=0, **kwargs)
        self.poll_count = 0

    def poll(self):
        self.poll_count += 1
        return None if self.poll_count < 7 else self.returncode


class CancellableFakePopen(FakePopen):
    def __init__(self, command, **kwargs):
        super().__init__(command, stdout_text="", stderr_text="", returncode=0, **kwargs)
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.returncode = GALLERY_DL_CANCELLED_RETURN_CODE
        return self.returncode


def make_config(project_tmp_path, *, proxy_enabled=False, cookies=None, yt_dlp_executable=None):
    return AppConfig(
        gallery_dl_executable="py -m gallery_dl",
        yt_dlp_executable=yt_dlp_executable,
        staging_dir=project_tmp_path / "staging",
        archive_db=project_tmp_path / "cache" / "gallery-dl-archive.sqlite3",
        imported_state=project_tmp_path / "cache" / "eagle-imported.json",
        eagle_api_base="http://localhost:41595",
        default_eagle_root_folder="Instagram",
        title_caption_chars=20,
        proxy=ProxyConfig(
            enabled=proxy_enabled,
            http_proxy="http://127.0.0.1:10809",
            https_proxy="http://127.0.0.1:10809",
            mode="manual" if proxy_enabled else "none",
        ),
        download=DownloadConfig(sleep_request="8-15", max_posts=50),
        cookies=cookies or CookiesConfig(),
    )


def test_build_author_gallery_dl_request_uses_username_directory(project_tmp_path):
    config = make_config(project_tmp_path)

    request = build_gallery_dl_request(config, "https://www.instagram.com/quinn.xyz/")

    assert request.mode == "author"
    assert request.url == "https://www.instagram.com/quinn.xyz/"
    assert request.target_dir == project_tmp_path / "staging" / "quinn.xyz"
    assert "--config-ignore" in request.command
    assert str(config.archive_db) in request.command
    assert "--write-metadata" in request.command
    assert str(request.target_dir) in request.command


def test_build_post_gallery_dl_request_uses_unknown_shortcode_directory(project_tmp_path):
    config = make_config(project_tmp_path)

    request = build_gallery_dl_request(config, "https://www.instagram.com/p/DYld7hQCT90/?img_index=1")

    assert request.mode == "post"
    assert request.url == "https://www.instagram.com/p/DYld7hQCT90/"
    assert request.target_dir == project_tmp_path / "staging" / "unknown" / "DYld7hQCT90"
    assert request.command[-1] == "https://www.instagram.com/p/DYld7hQCT90/"
    assert "--range" not in request.command


def test_build_gallery_dl_request_can_ignore_archive(project_tmp_path):
    config = make_config(project_tmp_path)

    request = build_gallery_dl_request(
        config,
        "https://www.instagram.com/p/DYld7hQCT90/",
        ignore_archive=True,
    )

    assert "--download-archive" not in request.command
    assert str(config.archive_db) not in request.command


def test_build_gallery_dl_request_can_enable_verbose(project_tmp_path):
    config = make_config(project_tmp_path)

    request = build_gallery_dl_request(
        config,
        "https://www.instagram.com/p/DYld7hQCT90/",
        verbose=True,
    )

    assert "--verbose" in request.command


def test_build_gallery_dl_request_can_override_max_posts(project_tmp_path):
    config = make_config(project_tmp_path)

    request = build_gallery_dl_request(
        config,
        "https://www.instagram.com/quinn.xyz/",
        max_posts=12,
    )

    range_index = request.command.index("--range")
    assert request.command[range_index + 1] == "1-12"


def test_build_gallery_dl_request_omits_range_for_unlimited_author_sync(project_tmp_path):
    config = make_config(project_tmp_path)

    request = build_gallery_dl_request(
        config,
        "https://www.instagram.com/quinn.xyz/",
        max_posts=-1,
    )

    assert "--range" not in request.command


def test_build_gallery_dl_request_adds_author_date_filters(project_tmp_path):
    config = make_config(project_tmp_path)

    with (
        patch("ins_eagle_sync.gallerydl_runner.resolve_gallery_dl_command", return_value=["py", "-m", "gallery_dl"]),
        patch("ins_eagle_sync.gallerydl_runner.gallery_dl_supports_date_options", return_value=True) as support_mock,
    ):
        request = build_gallery_dl_request(
            config,
            "https://www.instagram.com/quinn.xyz/",
            max_posts=-1,
            date_from="2026-01-01",
            date_to="2026-02-01",
        )

    assert "--range" not in request.command
    assert request.command[request.command.index("--date-after") + 1] == "2026-01-01"
    assert request.command[request.command.index("--date-before") + 1] == "2026-02-01"
    assert "--post-filter" not in request.command
    support_mock.assert_called_once_with(("py", "-m", "gallery_dl"))


def test_build_gallery_dl_request_falls_back_to_post_filter_with_safety_range(project_tmp_path):
    config = make_config(project_tmp_path)

    with patch("ins_eagle_sync.gallerydl_runner.gallery_dl_supports_date_options", return_value=False):
        request = build_gallery_dl_request(
            config,
            "https://www.instagram.com/quinn.xyz/",
            max_posts=-1,
            date_from="2026-01-01",
            date_to="2026-02-01",
        )

    assert "--date-after" not in request.command
    assert "--date-before" not in request.command
    assert request.command[request.command.index("--range") + 1] == f"1-{DATE_FILTER_FALLBACK_MAX_POSTS}"
    assert request.command[request.command.index("--terminate") + 1] == str(DATE_FILTER_FALLBACK_TERMINATE_SKIPS)
    post_filter = request.command[request.command.index("--post-filter") + 1]
    assert "date >= datetime(2026, 1, 1, 0, 0, 0)" in post_filter
    assert "date < datetime(2026, 2, 1, 0, 0, 0)" in post_filter


def test_build_gallery_dl_request_keeps_explicit_range_with_post_filter(project_tmp_path):
    config = make_config(project_tmp_path)

    with patch("ins_eagle_sync.gallerydl_runner.gallery_dl_supports_date_options", return_value=False):
        request = build_gallery_dl_request(
            config,
            "https://www.instagram.com/quinn.xyz/",
            max_posts=123,
            date_from="2026-01-01",
            date_to="2026-02-01",
        )

    assert request.command[request.command.index("--range") + 1] == "1-123"
    assert "--post-filter" in request.command
    assert "--terminate" not in request.command


def test_gallery_dl_date_filter_supports_iso_datetime_and_timestamp():
    assert build_gallery_dl_date_filter(date_from="2026-01-01T12:30:05", date_to=None) == (
        "date and date >= datetime(2026, 1, 1, 12, 30, 5)"
    )
    assert build_gallery_dl_date_filter(date_from=None, date_to="1767225600") == (
        "date and date < datetime(2026, 1, 1, 0, 0, 0)"
    )


def test_build_gallery_dl_request_rejects_invalid_date_filter(project_tmp_path):
    config = make_config(project_tmp_path)

    try:
        build_gallery_dl_request(config, "https://www.instagram.com/quinn.xyz/", date_from="not-a-date")
    except ValueError as exc:
        assert "date_from must be an ISO date" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_build_gallery_dl_request_rejects_invalid_max_posts(project_tmp_path):
    config = make_config(project_tmp_path)

    try:
        build_gallery_dl_request(config, "https://www.instagram.com/quinn.xyz/", max_posts=0)
    except ValueError as exc:
        assert "max_posts must be -1 or greater than 0" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_dry_run_logs_command_without_calling_subprocess(project_tmp_path):
    config = make_config(project_tmp_path)
    logs = []

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.Popen") as popen_mock:
        result = run_gallery_dl(
            config,
            "https://www.instagram.com/reel/DYld7hQCT90/",
            dry_run=True,
            log=logs.append,
        )

    assert result is None
    popen_mock.assert_not_called()
    assert any("gallery-dl mode: post" in line for line in logs)
    assert any("target URL: https://www.instagram.com/reel/DYld7hQCT90/" in line for line in logs)
    assert any("command:" in line for line in logs)


def test_dry_run_logs_date_filter_fallback_hint(project_tmp_path):
    config = make_config(project_tmp_path)
    logs = []

    with (
        patch("ins_eagle_sync.gallerydl_runner.gallery_dl_supports_date_options", return_value=False),
        patch("ins_eagle_sync.gallerydl_runner.subprocess.Popen") as popen_mock,
    ):
        result = run_gallery_dl(
            config,
            "https://www.instagram.com/quinn.xyz/",
            dry_run=True,
            max_posts=-1,
            date_from="2026-01-01",
            date_to="2026-02-01",
            log=logs.append,
        )

    assert result is None
    popen_mock.assert_not_called()
    assert DATE_FILTER_FALLBACK_HINT in logs


def test_run_gallery_dl_calls_subprocess_with_proxy_env(project_tmp_path):
    config = make_config(project_tmp_path, proxy_enabled=True)

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.Popen") as popen_mock:
        popen_mock.side_effect = lambda command, **kwargs: FakePopen(command, **kwargs)
        result = run_gallery_dl(
            config,
            "https://www.instagram.com/p/DYld7hQCT90/",
            log=lambda _message: None,
        )

    assert result.returncode == 0
    _, kwargs = popen_mock.call_args
    assert kwargs["stdout"] is not None
    assert kwargs["stderr"] is not None
    assert kwargs["text"] is True
    assert kwargs["env"]["HTTP_PROXY"] == "http://127.0.0.1:10809"
    assert kwargs["env"]["HTTPS_PROXY"] == "http://127.0.0.1:10809"


def test_build_subprocess_env_adds_packaged_ytdlp_to_path(project_tmp_path):
    tools_dir = project_tmp_path / "tools"
    tools_dir.mkdir()
    ytdlp = tools_dir / "yt-dlp.exe"
    ytdlp.write_bytes(b"")
    config = make_config(project_tmp_path, yt_dlp_executable=str(ytdlp))

    env = build_subprocess_env(config)

    assert env is not None
    assert str(tools_dir) in env["PATH"]


def test_build_gallery_dl_request_can_use_browser_cookies(project_tmp_path):
    config = make_config(
        project_tmp_path,
        cookies=CookiesConfig(enabled=True, from_browser="chrome"),
    )

    request = build_gallery_dl_request(config, "https://www.instagram.com/p/DYld7hQCT90/")

    assert "--cookies-from-browser" in request.command
    assert "chrome" in request.command


def test_build_gallery_dl_request_can_use_cookie_file(project_tmp_path):
    cookie_file = project_tmp_path / "instagram-cookies.txt"
    config = make_config(
        project_tmp_path,
        cookies=CookiesConfig(enabled=True, file=cookie_file),
    )

    request = build_gallery_dl_request(config, "https://www.instagram.com/p/DYld7hQCT90/")

    assert "--cookies" in request.command
    assert str(cookie_file) in request.command


def test_run_gallery_dl_missing_cookie_file_skips_subprocess(project_tmp_path):
    missing_cookie_file = project_tmp_path / "missing-cookies.txt"
    config = make_config(
        project_tmp_path,
        cookies=CookiesConfig(enabled=True, file=missing_cookie_file),
    )
    logs = []

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.Popen") as popen_mock:
        result = run_gallery_dl(
            config,
            "https://www.instagram.com/p/DYld7hQCT90/",
            log=logs.append,
        )

    assert result is not None
    assert result.returncode == 2
    popen_mock.assert_not_called()
    assert any("cookies.file does not exist" in line for line in logs)


def test_dry_run_with_missing_cookie_file_logs_warning(project_tmp_path):
    missing_cookie_file = project_tmp_path / "missing-cookies.txt"
    config = make_config(
        project_tmp_path,
        cookies=CookiesConfig(enabled=True, file=missing_cookie_file),
    )
    logs = []

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.Popen") as popen_mock:
        result = run_gallery_dl(
            config,
            "https://www.instagram.com/p/DYld7hQCT90/",
            dry_run=True,
            log=logs.append,
        )

    assert result is None
    popen_mock.assert_not_called()
    assert any("warning: cookies.file does not exist" in line for line in logs)


def test_run_gallery_dl_logs_subprocess_output(project_tmp_path):
    config = make_config(project_tmp_path)
    logs = []

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.Popen") as popen_mock:
        popen_mock.side_effect = lambda command, **kwargs: FakePopen(
            command,
            stdout_text="out text\n",
            stderr_text="err text\n",
            returncode=1,
            **kwargs,
        )
        result = run_gallery_dl(
            config,
            "https://www.instagram.com/p/DYld7hQCT90/",
            log=logs.append,
        )

    assert result.returncode == 1
    assert result.stdout == "out text\n"
    assert result.stderr == "err text\n"
    assert "gallery-dl exit code: 1" in logs
    assert "gallery-dl stdout:" in logs
    assert "out text" in logs
    assert "gallery-dl stderr:" in logs
    assert "err text" in logs


def test_run_gallery_dl_logs_login_redirect_hint(project_tmp_path):
    config = make_config(project_tmp_path)
    logs = []

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.Popen") as popen_mock:
        popen_mock.side_effect = lambda command, **kwargs: FakePopen(
            command,
            stderr_text="[instagram][error] HTTP redirect to login page (https://www.instagram.com/accounts/login/)\n",
            returncode=4,
            **kwargs,
        )
        run_gallery_dl(
            config,
            "https://www.instagram.com/p/DYld7hQCT90/",
            log=logs.append,
        )

    assert any("enable cookies" in line for line in logs)
    assert any("--config-ignore" in line for line in logs)


def test_run_gallery_dl_logs_cookie_permission_hint(project_tmp_path):
    config = make_config(project_tmp_path)
    stderr = (
            "[instagram][warning] cookies: [Errno 13] Permission denied: "
            "'C:\\Users\\EdisonSean\\AppData\\Local\\Google\\Chrome\\User Data\\Profile 2\\Network\\Cookies'"
    )
    logs = []

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.Popen") as popen_mock:
        popen_mock.side_effect = lambda command, **kwargs: FakePopen(
            command,
            stderr_text=stderr + "\n",
            returncode=4,
            **kwargs,
        )
        run_gallery_dl(
            config,
            "https://www.instagram.com/p/DYld7hQCT90/",
            log=logs.append,
        )

    assert any("could not use browser cookies" in line for line in logs)
    assert any("cookies.file" in line for line in logs)


def test_run_gallery_dl_logs_cookie_decryption_hint(project_tmp_path):
    config = make_config(project_tmp_path)
    stderr = (
            "[cookies][warning] Failed to decrypt cookie (DPAPI)\n"
            "[instagram][warning] cookies: 'NoneType' object has no attribute 'decode'"
    )
    logs = []

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.Popen") as popen_mock:
        popen_mock.side_effect = lambda command, **kwargs: FakePopen(
            command,
            stderr_text=stderr + "\n",
            returncode=4,
            **kwargs,
        )
        run_gallery_dl(
            config,
            "https://www.instagram.com/p/DYld7hQCT90/",
            log=logs.append,
        )

    assert any("could not use browser cookies" in line for line in logs)
    assert any("cookies.txt" in line for line in logs)


def test_run_gallery_dl_logs_cdn_timeout_hint_without_failing_warning(project_tmp_path):
    config = make_config(project_tmp_path)
    logs = []
    stderr = (
        "[downloader.http][warning] HTTPSConnectionPool(host='instagram.fabc1-1.fna.fbcdn.net', port=443): "
        "Read timed out."
    )

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.Popen") as popen_mock:
        popen_mock.side_effect = lambda command, **kwargs: FakePopen(
            command,
            stderr_text=stderr + "\n",
            returncode=0,
            **kwargs,
        )
        result = run_gallery_dl(
            config,
            "https://www.instagram.com/p/DYld7hQCT90/",
            log=logs.append,
        )

    assert result is not None
    assert result.returncode == 0
    assert any("Instagram CDN 下载超时" in line for line in logs)


def test_ytdlp_missing_warning_logs_friendly_hint():
    logs = []
    text = "[downloader.ytdl][error] Cannot import yt-dlp or youtube-dl"

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.Popen") as popen_mock:
        popen_mock.side_effect = lambda command, **kwargs: FakePopen(
            command,
            stderr_text=text + "\n",
            returncode=0,
            **kwargs,
        )
        result = run_subprocess_realtime(["gallery-dl"], env=None, log=logs.append)

    assert result.returncode == 0
    assert is_ytdlp_missing_warning(text)
    assert YTDLP_MISSING_HINT in logs


def test_run_subprocess_realtime_logs_no_output_progress(monkeypatch):
    logs = []
    times = iter([0, 61, 121, 122, 123, 124, 125, 126])
    monkeypatch.setattr("ins_eagle_sync.gallerydl_runner.time.monotonic", lambda: next(times, 126))

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.Popen") as popen_mock:
        popen_mock.side_effect = lambda command, **kwargs: SilentFakePopen(command, **kwargs)
        result = run_subprocess_realtime(["py"], env=None, log=logs.append)

    assert result.returncode == 0
    assert "下载仍在进行。" in logs
    assert "可能卡住。" in logs


def test_run_subprocess_realtime_terminates_when_cancelled():
    logs = []
    cancel_event = type("CancelEvent", (), {"is_set": lambda self: True})()
    process_holder = {}

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.Popen") as popen_mock:
        def make_process(command, **kwargs):
            process = CancellableFakePopen(command, **kwargs)
            process_holder["process"] = process
            return process

        popen_mock.side_effect = make_process
        result = run_subprocess_realtime(["gallery-dl"], env=None, log=logs.append, cancel_event=cancel_event)

    assert result.returncode == GALLERY_DL_CANCELLED_RETURN_CODE
    assert process_holder["process"].terminated is True
    assert GALLERY_DL_CANCELLED_HINT in logs


def test_proxy_env_is_none_when_proxy_disabled(project_tmp_path):
    config = make_config(project_tmp_path, proxy_enabled=False)

    env = build_subprocess_env(config)

    assert env is not None
    assert "HTTP_PROXY" not in env
    assert "HTTPS_PROXY" not in env


def test_cookie_values_are_hidden_in_logged_command():
    command = ["py", "-m", "gallery_dl", "--cookies", "secret.txt", "--cookies-from-browser=chrome"]

    logged = format_command_for_log(command)

    assert "secret.txt" not in logged
    assert "--cookies <hidden>" in logged
    assert "--cookies-from-browser=<hidden>" in logged
