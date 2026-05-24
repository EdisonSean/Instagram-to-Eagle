import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ins_eagle_sync.config import load_config
from ins_eagle_sync import services


def write_test_config(path, project_tmp_path, *, title_caption_chars=70):
    path.write_text(
        json.dumps(
            {
                "gallery_dl_executable": "py -m gallery_dl",
                "staging_dir": str(project_tmp_path / "staging"),
                "archive_db": str(project_tmp_path / "archive.sqlite3"),
                "imported_state": str(project_tmp_path / "imported.json"),
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
    return load_config(path)


def make_item(project_tmp_path):
    return type(
        "FakeImportItem",
        (),
        {
            "file_path": project_tmp_path / "image.jpg",
            "title": "Caption",
            "website": "https://www.instagram.com/p/ABC123/",
            "tags": ["instagram", "author:user"],
            "unique_key": "instagram:user:ABC123:01",
        },
    )()


def import_result(**overrides):
    data = {
        "total": 1,
        "skipped": 0,
        "imported": 1,
        "failed": 0,
        "failures": [],
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_parse_staging_service_returns_structured_items(project_tmp_path):
    config = write_test_config(project_tmp_path / "config.json", project_tmp_path)
    item = make_item(project_tmp_path)

    with patch("ins_eagle_sync.services.scan_staging_dir", return_value=[item]) as scan_mock:
        result = services.parse_staging(config, project_tmp_path / "stage")

    assert result["ok"] is True
    assert result["total"] == 1
    assert result["items"][0]["unique_key"] == item.unique_key
    scan_mock.assert_called_once_with(project_tmp_path / "stage", title_caption_chars=70)


def test_import_staging_service_can_be_called_directly(project_tmp_path):
    config = write_test_config(project_tmp_path / "config.json", project_tmp_path)
    item = make_item(project_tmp_path)

    with (
        patch("ins_eagle_sync.services.scan_staging_dir", return_value=[item]),
        patch("ins_eagle_sync.services.EagleClient"),
        patch("ins_eagle_sync.services.ImportedState.load"),
        patch("ins_eagle_sync.services.import_staging_items", return_value=import_result()) as import_mock,
    ):
        result = services.import_staging(config, project_tmp_path / "stage", folder_id="folder-1")

    assert result["ok"] is True
    assert result["total"] == 1
    assert result["imported"] == 1
    assert import_mock.call_args.kwargs["folder_id"] == "folder-1"


def test_sync_post_service_downloads_then_imports(project_tmp_path):
    config = write_test_config(project_tmp_path / "config.json", project_tmp_path)
    item = make_item(project_tmp_path)
    request = SimpleNamespace(target_dir=project_tmp_path / "staging" / "unknown" / "ABC123")

    with (
        patch("ins_eagle_sync.services.build_gallery_dl_request", return_value=request) as request_mock,
        patch("ins_eagle_sync.services.run_gallery_dl", return_value=None) as run_mock,
        patch("ins_eagle_sync.services.scan_staging_dir", return_value=[item]),
        patch("ins_eagle_sync.services.EagleClient"),
        patch("ins_eagle_sync.services.ImportedState.load"),
        patch("ins_eagle_sync.services.import_staging_items", return_value=import_result()),
    ):
        result = services.sync_post(
            config,
            "https://www.instagram.com/p/ABC123/",
            folder_id="folder-1",
            dry_run=True,
            ignore_archive=True,
            verbose_gallery_dl=True,
        )

    assert result["ok"] is True
    request_mock.assert_called_once()
    assert request_mock.call_args.kwargs["ignore_archive"] is True
    assert run_mock.call_args.kwargs["dry_run"] is True


def test_sync_author_service_passes_max_posts(project_tmp_path):
    config = write_test_config(project_tmp_path / "config.json", project_tmp_path)
    request = SimpleNamespace(target_dir=project_tmp_path / "staging" / "quinn.xyz")

    with (
        patch("ins_eagle_sync.services.build_gallery_dl_request", return_value=request) as request_mock,
        patch("ins_eagle_sync.services.run_gallery_dl", return_value=None) as run_mock,
        patch("ins_eagle_sync.services.scan_staging_dir", return_value=[]),
        patch("ins_eagle_sync.services.EagleClient"),
        patch("ins_eagle_sync.services.ImportedState.load"),
        patch("ins_eagle_sync.services.import_staging_items", return_value=import_result(total=0, imported=0)),
    ):
        result = services.sync_author(
            config,
            "https://www.instagram.com/quinn.xyz/",
            folder_id="folder-1",
            max_posts=12,
        )

    assert result["ok"] is True
    assert request_mock.call_args.kwargs["max_posts"] == 12
    assert run_mock.call_args.kwargs["max_posts"] == 12


def test_verify_imports_service_returns_structured_counts(project_tmp_path):
    config = write_test_config(project_tmp_path / "config.json", project_tmp_path)
    verify_result = SimpleNamespace(
        checked=2,
        alive=1,
        missing=1,
        alive_but_not_in_folder=0,
        unknown=0,
        removed=0,
    )

    with (
        patch("ins_eagle_sync.services.EagleClient"),
        patch("ins_eagle_sync.services.ImportedState.load"),
        patch("ins_eagle_sync.services.verify_import_records", return_value=verify_result),
    ):
        result = services.verify_imports(config, shortcode="ABC123", folder_id="folder-1", dry_run=True)

    assert result["ok"] is True
    assert result["checked"] == 2
    assert result["missing"] == 1


def test_forget_import_service_can_be_called_directly(project_tmp_path):
    config = write_test_config(project_tmp_path / "config.json", project_tmp_path)
    config.imported_state.write_text(
        json.dumps({"instagram:user:ABC123:01": {"title": "one"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = services.forget_import(config, shortcode="ABC123")

    assert result["ok"] is True
    assert result["matched_count"] == 1
    assert result["removed_count"] == 1


def test_list_folders_service_can_be_called_directly(project_tmp_path):
    config = write_test_config(project_tmp_path / "config.json", project_tmp_path)
    folders = [{"id": "folder-1", "name": "Instagram", "parent_id": None, "path": "Instagram"}]
    fake_eagle = type("FakeEagle", (), {"list_folders": lambda self: folders})()

    with patch("ins_eagle_sync.services.EagleClient", return_value=fake_eagle):
        result = services.list_folders(config)

    assert result["ok"] is True
    assert result["folders"] == folders


def test_ensure_folder_service_can_be_called_directly(project_tmp_path):
    config = write_test_config(project_tmp_path / "config.json", project_tmp_path)
    fake_eagle = type("FakeEagle", (), {"ensure_folder_path": lambda self, path: "folder-1"})()

    with patch("ins_eagle_sync.services.EagleClient", return_value=fake_eagle):
        result = services.ensure_folder(config, "Instagram/quinn.xyz")

    assert result["ok"] is True
    assert result["folder_id"] == "folder-1"
