import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ins_eagle_sync.cli import main


def write_test_config(path, project_tmp_path, *, title_caption_chars=70):
    state_path = project_tmp_path / "imported.json"
    path.write_text(
        json.dumps(
            {
                "gallery_dl_executable": "py -m gallery_dl",
                "staging_dir": str(project_tmp_path / "staging"),
                "archive_db": str(project_tmp_path / "archive.sqlite3"),
                "imported_state": str(state_path),
                "eagle_api_base": "http://localhost:41595",
                "default_eagle_root_folder": "Instagram",
                "title_caption_chars": title_caption_chars,
                "proxy": {"enabled": False},
                "cookies": {"enabled": False},
                "download": {"sleep_request": "8-15", "max_posts": 50},
            }
        ),
        encoding="utf-8",
    )


def test_run_dry_run_invokes_gallerydl_runner_with_normalized_url():
    with patch("ins_eagle_sync.cli.run_gallery_dl", return_value=None) as run_mock:
        exit_code = main(["run", "https://www.instagram.com/quinn.xyz/", "--dry-run"])

    assert exit_code == 0
    _, url = run_mock.call_args.args
    assert url == "https://www.instagram.com/quinn.xyz/"
    assert run_mock.call_args.kwargs["dry_run"] is True


def test_gui_command_opens_gui_without_loading_cli_config():
    with patch("ins_eagle_sync.gui.main") as gui_main:
        exit_code = main(["gui"])

    assert exit_code == 0
    gui_main.assert_called_once_with()


def test_parse_staging_prints_import_item_summary(project_tmp_path, capsys):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)
    service_result = {
        "ok": True,
        "total": 1,
        "items": [
            {
                "file_path": "E:\\stage\\item.jpg",
                "title": "Caption",
                "website": "https://www.instagram.com/p/ABC123/",
                "tags": ["instagram", "author:user"],
                "unique_key": "instagram:user:ABC123:01",
            }
        ],
        "messages": [],
    }

    with patch("ins_eagle_sync.cli.services.parse_staging", return_value=service_result) as service_mock:
        exit_code = main(["--config", str(config_path), "parse-staging", "E:/stage"])

    assert exit_code == 0
    assert service_mock.call_args.args[1] == "E:/stage"
    assert json.loads(capsys.readouterr().out) == service_result["items"]


def test_list_folders_cli_prints_folder_summary(project_tmp_path, capsys):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)
    folders = [
        {"id": "root-1", "name": "Instagram", "parent_id": None, "path": "Instagram"},
        {"id": "child-1", "name": "quinn.xyz", "parent_id": "root-1", "path": "Instagram/quinn.xyz"},
    ]

    with patch("ins_eagle_sync.cli.services.list_folders", return_value={"ok": True, "folders": folders, "messages": []}):
        exit_code = main(["--config", str(config_path), "list-folders"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == folders


def test_list_folders_cli_outputs_clear_error(project_tmp_path, capsys):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)

    with patch(
        "ins_eagle_sync.cli.services.list_folders",
        return_value={"ok": False, "messages": ["error: Eagle is not available"]},
    ):
        exit_code = main(["--config", str(config_path), "list-folders"])

    assert exit_code == 1
    assert "error: Eagle is not available" in capsys.readouterr().out


def test_ensure_folder_cli_prints_final_folder_id(project_tmp_path, capsys):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)

    with patch(
        "ins_eagle_sync.cli.services.ensure_folder",
        return_value={"ok": True, "folder_id": "folder-1", "messages": ["folder id: folder-1"]},
    ) as service_mock:
        exit_code = main(["--config", str(config_path), "ensure-folder", "Instagram/quinn.xyz"])

    assert exit_code == 0
    assert service_mock.call_args.args[1] == "Instagram/quinn.xyz"
    assert "folder id: folder-1" in capsys.readouterr().out


def test_import_staging_calls_service(project_tmp_path):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)

    with patch("ins_eagle_sync.cli.services.import_staging", return_value={"ok": True, "messages": []}) as service_mock:
        exit_code = main(
            [
                "--config",
                str(config_path),
                "import-staging",
                str(project_tmp_path / "staging"),
                "--folder-path",
                "Instagram/quinn.xyz",
                "--dry-run",
                "--verify-eagle",
            ]
        )

    assert exit_code == 0
    assert service_mock.call_args.args[1] == str(project_tmp_path / "staging")
    assert service_mock.call_args.kwargs["folder_path"] == "Instagram/quinn.xyz"
    assert service_mock.call_args.kwargs["dry_run"] is True
    assert service_mock.call_args.kwargs["verify_eagle"] is True


def test_import_staging_returns_1_when_service_fails(project_tmp_path):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)

    with patch("ins_eagle_sync.cli.services.import_staging", return_value={"ok": False, "messages": []}):
        exit_code = main(
            [
                "--config",
                str(config_path),
                "import-staging",
                str(project_tmp_path / "staging"),
                "--folder-id",
                "folder-1",
                "--folder-path",
                "Instagram/quinn.xyz",
            ]
        )

    assert exit_code == 1


def test_forget_import_cli_calls_service(project_tmp_path):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)

    with patch("ins_eagle_sync.cli.services.forget_import", return_value={"ok": True, "messages": []}) as service_mock:
        exit_code = main(
            [
                "--config",
                str(config_path),
                "forget-import",
                "--shortcode",
                "DYld7hQCT90",
                "--dry-run",
            ]
        )

    assert exit_code == 0
    assert service_mock.call_args.kwargs["shortcode"] == "DYld7hQCT90"
    assert service_mock.call_args.kwargs["dry_run"] is True


def test_verify_imports_cli_calls_service(project_tmp_path):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)

    with patch("ins_eagle_sync.cli.services.verify_imports", return_value={"ok": True, "messages": []}) as service_mock:
        exit_code = main(
            [
                "--config",
                str(config_path),
                "verify-imports",
                "--shortcode",
                "DYld7hQCT90",
                "--folder-id",
                "folder-1",
                "--dry-run",
            ]
        )

    assert exit_code == 0
    assert service_mock.call_args.kwargs["shortcode"] == "DYld7hQCT90"
    assert service_mock.call_args.kwargs["folder_id"] == "folder-1"
    assert service_mock.call_args.kwargs["folder_path"] is None
    assert service_mock.call_args.kwargs["dry_run"] is True


def test_verify_imports_cli_accepts_folder_path(project_tmp_path):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)

    with patch("ins_eagle_sync.cli.services.verify_imports", return_value={"ok": True, "messages": []}) as service_mock:
        exit_code = main(
            [
                "--config",
                str(config_path),
                "verify-imports",
                "--shortcode",
                "DYld7hQCT90",
                "--folder-path",
                "Instagram/quinn.xyz",
                "--dry-run",
            ]
        )

    assert exit_code == 0
    assert service_mock.call_args.kwargs["shortcode"] == "DYld7hQCT90"
    assert service_mock.call_args.kwargs["folder_id"] is None
    assert service_mock.call_args.kwargs["folder_path"] == "Instagram/quinn.xyz"
    assert service_mock.call_args.kwargs["dry_run"] is True


def test_verify_imports_cli_without_folder_keeps_existing_behavior(project_tmp_path):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)

    with patch("ins_eagle_sync.cli.services.verify_imports", return_value={"ok": True, "messages": []}) as service_mock:
        exit_code = main(
            [
                "--config",
                str(config_path),
                "verify-imports",
                "--shortcode",
                "DYld7hQCT90",
            ]
        )

    assert exit_code == 0
    assert service_mock.call_args.kwargs["folder_id"] is None
    assert service_mock.call_args.kwargs["folder_path"] is None


def test_sync_post_calls_service(project_tmp_path):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)

    with patch("ins_eagle_sync.cli.services.sync_posts", return_value={"ok": True, "messages": []}) as service_mock:
        exit_code = main(
            [
                "--config",
                str(config_path),
                "sync-post",
                "https://www.instagram.com/p/ABC123/?img_index=1",
                "--folder-path",
                "Instagram/quinn.xyz",
                "--dry-run",
                "--verify-eagle",
                "--ignore-archive",
                "--verbose-gallery-dl",
            ]
        )

    assert exit_code == 0
    assert service_mock.call_args.args[1] == "https://www.instagram.com/p/ABC123/?img_index=1"
    assert service_mock.call_args.kwargs["folder_path"] == "Instagram/quinn.xyz"
    assert service_mock.call_args.kwargs["dry_run"] is True
    assert service_mock.call_args.kwargs["verify_eagle"] is True
    assert service_mock.call_args.kwargs["ignore_archive"] is True
    assert service_mock.call_args.kwargs["verbose_gallery_dl"] is True


def test_sync_post_cli_accepts_multiple_post_urls(project_tmp_path):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)

    with patch("ins_eagle_sync.cli.services.sync_posts", return_value={"ok": True, "messages": []}) as service_mock:
        exit_code = main(
            [
                "--config",
                str(config_path),
                "sync-post",
                "https://www.instagram.com/p/ABC123/",
                "https://www.instagram.com/reel/DEF456/",
                "--folder-id",
                "folder-1",
            ]
        )

    assert exit_code == 0
    assert service_mock.call_args.args[1] == "https://www.instagram.com/p/ABC123/ https://www.instagram.com/reel/DEF456/"


def test_sync_post_returns_gallery_dl_failure_code(project_tmp_path):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)

    with patch(
        "ins_eagle_sync.cli.services.sync_posts",
        return_value={"ok": False, "returncode": 4, "messages": []},
    ):
        exit_code = main(
            [
                "--config",
                str(config_path),
                "sync-post",
                "https://www.instagram.com/p/ABC123/",
                "--folder-id",
                "folder-1",
            ]
        )

    assert exit_code == 4


def test_sync_author_calls_service(project_tmp_path):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)

    with patch("ins_eagle_sync.cli.services.sync_author", return_value={"ok": True, "messages": []}) as service_mock:
        exit_code = main(
            [
                "--config",
                str(config_path),
                "sync-author",
                "https://www.instagram.com/quinn.xyz/?hl=en",
                "--folder-path",
                "Instagram/quinn.xyz",
                "--dry-run",
                "--force",
                "--verify-eagle",
                "--max-posts",
                "12",
                "--date-from",
                "2026-01-01",
                "--date-to",
                "2026-02-01",
                "--show-annotation",
                "--ignore-archive",
                "--verbose-gallery-dl",
            ]
        )

    assert exit_code == 0
    assert service_mock.call_args.args[1] == "https://www.instagram.com/quinn.xyz/"
    assert service_mock.call_args.kwargs["folder_path"] == "Instagram/quinn.xyz"
    assert service_mock.call_args.kwargs["dry_run"] is True
    assert service_mock.call_args.kwargs["force"] is True
    assert service_mock.call_args.kwargs["verify_eagle"] is True
    assert service_mock.call_args.kwargs["max_posts"] == 12
    assert service_mock.call_args.kwargs["date_from"] == "2026-01-01"
    assert service_mock.call_args.kwargs["date_to"] == "2026-02-01"
    assert service_mock.call_args.kwargs["show_annotation"] is True


def test_sync_author_cli_accepts_unlimited_max_posts(project_tmp_path):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)

    with patch("ins_eagle_sync.cli.services.sync_author", return_value={"ok": True, "messages": []}) as service_mock:
        exit_code = main(
            [
                "--config",
                str(config_path),
                "sync-author",
                "https://www.instagram.com/quinn.xyz/",
                "--folder-id",
                "folder-1",
                "--max-posts",
                "-1",
            ]
        )

    assert exit_code == 0
    assert service_mock.call_args.kwargs["max_posts"] == -1
