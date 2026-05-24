import json
import sys
from pathlib import Path
from subprocess import CompletedProcess
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


def test_parse_staging_prints_import_item_summary(project_tmp_path, capsys):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)
    fake_item = type(
        "FakeImportItem",
        (),
        {
            "file_path": Path("E:/stage/item.jpg"),
            "title": "Caption",
            "website": "https://www.instagram.com/p/ABC123/",
            "tags": ["instagram", "author:user"],
            "unique_key": "instagram:user:ABC123:01",
        },
    )()

    with patch("ins_eagle_sync.cli.scan_staging_dir", return_value=[fake_item]) as scan_mock:
        exit_code = main(["--config", str(config_path), "parse-staging", "E:/stage"])

    assert exit_code == 0
    scan_mock.assert_called_once_with(Path("E:/stage"), title_caption_chars=70)
    output = json.loads(capsys.readouterr().out)
    assert output == [
        {
            "file_path": "E:\\stage\\item.jpg",
            "title": "Caption",
            "website": "https://www.instagram.com/p/ABC123/",
            "tags": ["instagram", "author:user"],
            "unique_key": "instagram:user:ABC123:01",
        }
    ]


def test_import_staging_dry_run_uses_state_and_importer(project_tmp_path):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)

    with (
        patch("ins_eagle_sync.cli.scan_staging_dir", return_value=[]) as scan_mock,
        patch("ins_eagle_sync.cli.import_staging_items") as import_mock,
    ):
        import_mock.return_value.failed = 0
        exit_code = main(
            [
                "--config",
                str(config_path),
                "import-staging",
                str(project_tmp_path / "staging"),
                "--folder-id",
                "folder-1",
                "--dry-run",
            ]
        )

    assert exit_code == 0
    scan_mock.assert_called_once_with(project_tmp_path / "staging", title_caption_chars=70)
    assert import_mock.call_args.kwargs["folder_id"] == "folder-1"
    assert import_mock.call_args.kwargs["dry_run"] is True


def test_forget_import_cli_dry_run_does_not_modify_state(project_tmp_path, capsys):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)
    state_path = project_tmp_path / "imported.json"
    original_records = {
        "instagram:quinn.xyz:DYld7hQCT90:01": {"title": "one"},
        "instagram:quinn.xyz:DYld7hQCT90:02": {"title": "two"},
    }
    state_path.write_text(json.dumps(original_records, ensure_ascii=False, indent=2), encoding="utf-8")

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
    assert json.loads(state_path.read_text(encoding="utf-8")) == original_records
    output = capsys.readouterr().out
    assert "matched count: 2" in output
    assert "removed count: 0" in output
    assert "instagram:quinn.xyz:DYld7hQCT90:01" in output


def test_forget_import_cli_missing_record_outputs_clear_message(project_tmp_path, capsys):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)
    state_path = project_tmp_path / "imported.json"
    state_path.write_text("{}", encoding="utf-8")

    exit_code = main(
        [
            "--config",
            str(config_path),
            "forget-import",
            "--unique-key",
            "instagram:quinn.xyz:MISSING:01",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "matched count: 0" in output
    assert "No imported records matched" in output


def test_sync_post_dry_run_prints_download_and_import_plan(project_tmp_path):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)
    target_dir = project_tmp_path / "staging" / "unknown" / "ABC123"
    request = type("FakeRequest", (), {"target_dir": target_dir})()

    with (
        patch("ins_eagle_sync.cli.build_gallery_dl_request", return_value=request) as request_mock,
        patch("ins_eagle_sync.cli.run_gallery_dl", return_value=None) as run_mock,
        patch("ins_eagle_sync.cli.scan_staging_dir", return_value=[]) as scan_mock,
        patch("ins_eagle_sync.cli.import_staging_items") as import_mock,
    ):
        import_mock.return_value.failed = 0
        exit_code = main(
            [
                "--config",
                str(config_path),
                "sync-post",
                "https://www.instagram.com/p/ABC123/",
                "--folder-id",
                "folder-1",
                "--dry-run",
                "--show-annotation",
                "--ignore-archive",
                "--verbose-gallery-dl",
            ]
        )

    assert exit_code == 0
    request_mock.assert_called_once()
    assert request_mock.call_args.kwargs["ignore_archive"] is True
    assert request_mock.call_args.kwargs["verbose"] is True
    assert run_mock.call_args.kwargs["dry_run"] is True
    assert run_mock.call_args.kwargs["ignore_archive"] is True
    assert run_mock.call_args.kwargs["verbose"] is True
    scan_mock.assert_called_once_with(target_dir, title_caption_chars=70)
    assert import_mock.call_args.kwargs["dry_run"] is True
    assert import_mock.call_args.kwargs["show_annotation"] is True


def test_sync_post_gallery_dl_failure_does_not_import(project_tmp_path):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)
    target_dir = project_tmp_path / "staging" / "unknown" / "ABC123"
    request = type("FakeRequest", (), {"target_dir": target_dir})()

    with (
        patch("ins_eagle_sync.cli.build_gallery_dl_request", return_value=request),
        patch(
            "ins_eagle_sync.cli.run_gallery_dl",
            return_value=CompletedProcess(args=["py"], returncode=4, stdout="", stderr="login"),
        ),
        patch("ins_eagle_sync.cli.scan_staging_dir") as scan_mock,
        patch("ins_eagle_sync.cli.import_staging_items") as import_mock,
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
    scan_mock.assert_not_called()
    import_mock.assert_not_called()


def test_sync_post_success_imports_downloaded_staging_items(project_tmp_path):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)
    target_dir = project_tmp_path / "staging" / "unknown" / "ABC123"
    request = type("FakeRequest", (), {"target_dir": target_dir})()
    fake_item = object()

    with (
        patch("ins_eagle_sync.cli.build_gallery_dl_request", return_value=request),
        patch(
            "ins_eagle_sync.cli.run_gallery_dl",
            return_value=CompletedProcess(args=["py"], returncode=0, stdout="", stderr=""),
        ) as run_mock,
        patch("ins_eagle_sync.cli.scan_staging_dir", return_value=[fake_item]) as scan_mock,
        patch("ins_eagle_sync.cli.import_staging_items") as import_mock,
    ):
        import_mock.return_value.failed = 0
        exit_code = main(
            [
                "--config",
                str(config_path),
                "sync-post",
                "https://www.instagram.com/p/ABC123/",
                "--folder-id",
                "folder-1",
                "--force",
            ]
        )

    assert exit_code == 0
    assert run_mock.call_args.kwargs["dry_run"] is False
    scan_mock.assert_called_once_with(target_dir, title_caption_chars=70)
    assert import_mock.call_args.args[0] == [fake_item]
    assert import_mock.call_args.kwargs["folder_id"] == "folder-1"
    assert import_mock.call_args.kwargs["force"] is True


def test_sync_author_dry_run_prints_download_and_import_plan(project_tmp_path):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)
    target_dir = project_tmp_path / "staging" / "quinn.xyz"
    request = type("FakeRequest", (), {"target_dir": target_dir})()

    with (
        patch("ins_eagle_sync.cli.build_gallery_dl_request", return_value=request) as request_mock,
        patch("ins_eagle_sync.cli.run_gallery_dl", return_value=None) as run_mock,
        patch("ins_eagle_sync.cli.scan_staging_dir", return_value=[]) as scan_mock,
        patch("ins_eagle_sync.cli.import_staging_items") as import_mock,
    ):
        import_mock.return_value.failed = 0
        exit_code = main(
            [
                "--config",
                str(config_path),
                "sync-author",
                "https://www.instagram.com/quinn.xyz/",
                "--folder-id",
                "folder-1",
                "--dry-run",
                "--force",
                "--max-posts",
                "12",
                "--show-annotation",
                "--ignore-archive",
                "--verbose-gallery-dl",
            ]
        )

    assert exit_code == 0
    request_mock.assert_called_once()
    assert request_mock.call_args.args[1] == "https://www.instagram.com/quinn.xyz/"
    assert request_mock.call_args.kwargs["ignore_archive"] is True
    assert request_mock.call_args.kwargs["verbose"] is True
    assert request_mock.call_args.kwargs["max_posts"] == 12
    assert run_mock.call_args.kwargs["dry_run"] is True
    assert run_mock.call_args.kwargs["ignore_archive"] is True
    assert run_mock.call_args.kwargs["verbose"] is True
    assert run_mock.call_args.kwargs["max_posts"] == 12
    scan_mock.assert_called_once_with(target_dir, title_caption_chars=70)
    assert import_mock.call_args.kwargs["dry_run"] is True
    assert import_mock.call_args.kwargs["force"] is True
    assert import_mock.call_args.kwargs["show_annotation"] is True


def test_sync_author_gallery_dl_failure_does_not_import(project_tmp_path):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)
    target_dir = project_tmp_path / "staging" / "quinn.xyz"
    request = type("FakeRequest", (), {"target_dir": target_dir})()

    with (
        patch("ins_eagle_sync.cli.build_gallery_dl_request", return_value=request),
        patch(
            "ins_eagle_sync.cli.run_gallery_dl",
            return_value=CompletedProcess(args=["py"], returncode=4, stdout="", stderr="login"),
        ),
        patch("ins_eagle_sync.cli.scan_staging_dir") as scan_mock,
        patch("ins_eagle_sync.cli.import_staging_items") as import_mock,
    ):
        exit_code = main(
            [
                "--config",
                str(config_path),
                "sync-author",
                "https://www.instagram.com/quinn.xyz/",
                "--folder-id",
                "folder-1",
            ]
        )

    assert exit_code == 4
    scan_mock.assert_not_called()
    import_mock.assert_not_called()


def test_sync_author_success_imports_author_staging_items(project_tmp_path):
    config_path = project_tmp_path / "config.json"
    write_test_config(config_path, project_tmp_path)
    target_dir = project_tmp_path / "staging" / "quinn.xyz"
    request = type("FakeRequest", (), {"target_dir": target_dir})()
    fake_item = object()

    with (
        patch("ins_eagle_sync.cli.build_gallery_dl_request", return_value=request),
        patch(
            "ins_eagle_sync.cli.run_gallery_dl",
            return_value=CompletedProcess(args=["py"], returncode=0, stdout="", stderr=""),
        ) as run_mock,
        patch("ins_eagle_sync.cli.scan_staging_dir", return_value=[fake_item]) as scan_mock,
        patch("ins_eagle_sync.cli.import_staging_items") as import_mock,
    ):
        import_mock.return_value.failed = 0
        exit_code = main(
            [
                "--config",
                str(config_path),
                "sync-author",
                "https://www.instagram.com/quinn.xyz/",
                "--folder-id",
                "folder-1",
            ]
        )

    assert exit_code == 0
    assert run_mock.call_args.kwargs["dry_run"] is False
    scan_mock.assert_called_once_with(target_dir, title_caption_chars=70)
    assert import_mock.call_args.args[0] == [fake_item]
    assert import_mock.call_args.kwargs["folder_id"] == "folder-1"
