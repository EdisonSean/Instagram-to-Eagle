import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ins_eagle_sync.config import AppConfig, DownloadConfig, ProxyConfig
from ins_eagle_sync.gallerydl_runner import (
    build_gallery_dl_request,
    build_subprocess_env,
    format_command_for_log,
    run_gallery_dl,
)


def make_config(project_tmp_path, *, proxy_enabled=False):
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
    )


def test_build_author_gallery_dl_request_uses_username_directory(project_tmp_path):
    config = make_config(project_tmp_path)

    request = build_gallery_dl_request(config, "https://www.instagram.com/quinn.xyz/")

    assert request.mode == "author"
    assert request.url == "https://www.instagram.com/quinn.xyz/"
    assert request.target_dir == project_tmp_path / "staging" / "quinn.xyz"
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


def test_proxy_env_is_none_when_proxy_disabled(project_tmp_path):
    config = make_config(project_tmp_path, proxy_enabled=False)

    assert build_subprocess_env(config) is None


def test_cookie_values_are_hidden_in_logged_command():
    command = ["py", "-m", "gallery_dl", "--cookies", "secret.txt", "--cookies-from-browser=chrome"]

    logged = format_command_for_log(command)

    assert "secret.txt" not in logged
    assert "--cookies <hidden>" in logged
    assert "--cookies-from-browser=<hidden>" in logged
