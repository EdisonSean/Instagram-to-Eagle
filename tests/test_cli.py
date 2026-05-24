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
