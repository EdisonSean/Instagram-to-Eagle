import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ins_eagle_sync.config import AppConfig, CookiesConfig, DownloadConfig, ProxyConfig
from ins_eagle_sync.gallerydl_runner import (
    build_gallery_dl_request,
    build_subprocess_env,
    format_command_for_log,
    run_gallery_dl,
)


def make_config(project_tmp_path, *, proxy_enabled=False, cookies=None):
    return AppConfig(
        gallery_dl_executable="py -m gallery_dl",
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

    request = build_gallery_dl_request(config, "https://www.instagram.com/p/DYld7hQCT90/")

    assert request.mode == "post"
    assert request.url == "https://www.instagram.com/p/DYld7hQCT90/"
    assert request.target_dir == project_tmp_path / "staging" / "unknown" / "DYld7hQCT90"
    assert request.command[-1] == "https://www.instagram.com/p/DYld7hQCT90/"


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


def test_dry_run_logs_command_without_calling_subprocess(project_tmp_path):
    config = make_config(project_tmp_path)
    logs = []

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.run") as run_mock:
        result = run_gallery_dl(
            config,
            "https://www.instagram.com/reel/DYld7hQCT90/",
            dry_run=True,
            log=logs.append,
        )

    assert result is None
    run_mock.assert_not_called()
    assert any("gallery-dl mode: post" in line for line in logs)
    assert any("target URL: https://www.instagram.com/reel/DYld7hQCT90/" in line for line in logs)
    assert any("command:" in line for line in logs)


def test_run_gallery_dl_calls_subprocess_with_proxy_env(project_tmp_path):
    config = make_config(project_tmp_path, proxy_enabled=True)
    completed = CompletedProcess(args=["py"], returncode=0, stdout="", stderr="")

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.run", return_value=completed) as run_mock:
        result = run_gallery_dl(
            config,
            "https://www.instagram.com/p/DYld7hQCT90/",
            log=lambda _message: None,
        )

    assert result == completed
    _, kwargs = run_mock.call_args
    assert kwargs["check"] is False
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["env"]["HTTP_PROXY"] == "http://127.0.0.1:10809"
    assert kwargs["env"]["HTTPS_PROXY"] == "http://127.0.0.1:10809"


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

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.run") as run_mock:
        result = run_gallery_dl(
            config,
            "https://www.instagram.com/p/DYld7hQCT90/",
            log=logs.append,
        )

    assert result is not None
    assert result.returncode == 2
    run_mock.assert_not_called()
    assert any("cookies.file does not exist" in line for line in logs)


def test_dry_run_with_missing_cookie_file_logs_warning(project_tmp_path):
    missing_cookie_file = project_tmp_path / "missing-cookies.txt"
    config = make_config(
        project_tmp_path,
        cookies=CookiesConfig(enabled=True, file=missing_cookie_file),
    )
    logs = []

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.run") as run_mock:
        result = run_gallery_dl(
            config,
            "https://www.instagram.com/p/DYld7hQCT90/",
            dry_run=True,
            log=logs.append,
        )

    assert result is None
    run_mock.assert_not_called()
    assert any("warning: cookies.file does not exist" in line for line in logs)


def test_run_gallery_dl_logs_subprocess_output(project_tmp_path):
    config = make_config(project_tmp_path)
    completed = CompletedProcess(args=["py"], returncode=1, stdout="out text", stderr="err text")
    logs = []

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.run", return_value=completed):
        result = run_gallery_dl(
            config,
            "https://www.instagram.com/p/DYld7hQCT90/",
            log=logs.append,
        )

    assert result == completed
    assert "gallery-dl exit code: 1" in logs
    assert "gallery-dl stdout:" in logs
    assert "out text" in logs
    assert "gallery-dl stderr:" in logs
    assert "err text" in logs


def test_run_gallery_dl_logs_login_redirect_hint(project_tmp_path):
    config = make_config(project_tmp_path)
    completed = CompletedProcess(
        args=["py"],
        returncode=4,
        stdout="",
        stderr="[instagram][error] HTTP redirect to login page (https://www.instagram.com/accounts/login/)",
    )
    logs = []

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.run", return_value=completed):
        run_gallery_dl(
            config,
            "https://www.instagram.com/p/DYld7hQCT90/",
            log=logs.append,
        )

    assert any("enable cookies" in line for line in logs)
    assert any("--config-ignore" in line for line in logs)


def test_run_gallery_dl_logs_cookie_permission_hint(project_tmp_path):
    config = make_config(project_tmp_path)
    completed = CompletedProcess(
        args=["py"],
        returncode=4,
        stdout="",
        stderr=(
            "[instagram][warning] cookies: [Errno 13] Permission denied: "
            "'C:\\Users\\EdisonSean\\AppData\\Local\\Google\\Chrome\\User Data\\Profile 2\\Network\\Cookies'"
        ),
    )
    logs = []

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.run", return_value=completed):
        run_gallery_dl(
            config,
            "https://www.instagram.com/p/DYld7hQCT90/",
            log=logs.append,
        )

    assert any("could not use browser cookies" in line for line in logs)
    assert any("cookies.file" in line for line in logs)


def test_run_gallery_dl_logs_cookie_decryption_hint(project_tmp_path):
    config = make_config(project_tmp_path)
    completed = CompletedProcess(
        args=["py"],
        returncode=4,
        stdout="",
        stderr=(
            "[cookies][warning] Failed to decrypt cookie (DPAPI)\n"
            "[instagram][warning] cookies: 'NoneType' object has no attribute 'decode'"
        ),
    )
    logs = []

    with patch("ins_eagle_sync.gallerydl_runner.subprocess.run", return_value=completed):
        run_gallery_dl(
            config,
            "https://www.instagram.com/p/DYld7hQCT90/",
            log=logs.append,
        )

    assert any("could not use browser cookies" in line for line in logs)
    assert any("cookies.txt" in line for line in logs)


def test_proxy_env_is_none_when_proxy_disabled(project_tmp_path):
    config = make_config(project_tmp_path, proxy_enabled=False)

    assert build_subprocess_env(config) is None


def test_cookie_values_are_hidden_in_logged_command():
    command = ["py", "-m", "gallery_dl", "--cookies", "secret.txt", "--cookies-from-browser=chrome"]

    logged = format_command_for_log(command)

    assert "secret.txt" not in logged
    assert "--cookies <hidden>" in logged
    assert "--cookies-from-browser=<hidden>" in logged
