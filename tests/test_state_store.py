import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ins_eagle_sync.state_store import ImportedState, import_key


def test_import_key_uses_shortcode_and_media_index():
    assert import_key("ABC123", 3) == "ABC123:3"


def test_state_store_round_trip(project_tmp_path):
    path = project_tmp_path / "state" / "imported.json"
    state = ImportedState.load(path)

    assert not state.has_imported("ABC123", 1)

    state.mark_imported("ABC123", 1)
    state.save()

    loaded = ImportedState.load(path)
    assert loaded.has_imported("ABC123", 1)
    assert not loaded.has_imported("ABC123", 2)


def test_state_store_writes_unique_key_records(project_tmp_path):
    path = project_tmp_path / "state" / "imported.json"
    state = ImportedState.load(path)
    item = type(
        "FakeImportItem",
        (),
        {
            "unique_key": "instagram:user:ABC123:01",
            "file_path": Path("image.jpg"),
            "website": "https://www.instagram.com/p/ABC123/",
            "title": "Title",
        },
    )()

    state.mark_item_imported(item, eagle_item_id="eagle-1", imported_at="2026-01-01T00:00:00+00:00")
    state.save()

    loaded = ImportedState.load(path)
    assert loaded.has_unique_key("instagram:user:ABC123:01")
    assert loaded.records["instagram:user:ABC123:01"] == {
        "file_path": "image.jpg",
        "website": "https://www.instagram.com/p/ABC123/",
        "title": "Title",
        "eagle_item_id": "eagle-1",
        "imported_at": "2026-01-01T00:00:00+00:00",
    }


def test_state_store_writes_folder_id_when_provided(project_tmp_path):
    path = project_tmp_path / "state" / "imported.json"
    state = ImportedState.load(path)
    item = type(
        "FakeImportItem",
        (),
        {
            "unique_key": "instagram:user:ABC123:01",
            "file_path": Path("image.jpg"),
            "website": "https://www.instagram.com/p/ABC123/",
            "title": "Title",
        },
    )()

    state.mark_item_imported(
        item,
        eagle_item_id="eagle-1",
        folder_id="folder-1",
        imported_at="2026-01-01T00:00:00+00:00",
    )
    state.save()

    loaded = ImportedState.load(path)
    assert loaded.records["instagram:user:ABC123:01"]["folder_id"] == "folder-1"


def write_state(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sample_import_records():
    return {
        "instagram:quinn.xyz:DYld7hQCT90:01": {"title": "one"},
        "instagram:quinn.xyz:DYld7hQCT90:02": {"title": "two"},
        "instagram:quinn.xyz:DYld7hQCT90:03": {"title": "three"},
        "instagram:other:OTHER123:01": {"title": "other"},
    }


def test_forget_by_shortcode_removes_all_matching_records(project_tmp_path):
    path = project_tmp_path / "state" / "imported.json"
    write_state(path, sample_import_records())
    state = ImportedState.load(path)

    result = state.forget(shortcode="DYld7hQCT90")

    assert result.matched_count == 3
    assert result.removed_count == 3
    assert result.removed_keys == [
        "instagram:quinn.xyz:DYld7hQCT90:01",
        "instagram:quinn.xyz:DYld7hQCT90:02",
        "instagram:quinn.xyz:DYld7hQCT90:03",
    ]
    assert result.backup_path == path.with_name("imported.json.bak")
    assert result.backup_path.exists()

    loaded = ImportedState.load(path)
    assert "instagram:quinn.xyz:DYld7hQCT90:01" not in loaded.records
    assert "instagram:other:OTHER123:01" in loaded.records


def test_forget_by_username_and_shortcode(project_tmp_path):
    path = project_tmp_path / "state" / "imported.json"
    records = sample_import_records()
    records["instagram:other:DYld7hQCT90:01"] = {"title": "same shortcode other author"}
    write_state(path, records)
    state = ImportedState.load(path)

    result = state.forget(username="quinn.xyz", shortcode="DYld7hQCT90")

    assert result.removed_count == 3
    loaded = ImportedState.load(path)
    assert "instagram:other:DYld7hQCT90:01" in loaded.records


def test_forget_by_unique_key_removes_one_record(project_tmp_path):
    path = project_tmp_path / "state" / "imported.json"
    write_state(path, sample_import_records())
    state = ImportedState.load(path)

    result = state.forget(unique_key="instagram:quinn.xyz:DYld7hQCT90:02")

    assert result.matched_count == 1
    assert result.removed_count == 1
    assert result.removed_keys == ["instagram:quinn.xyz:DYld7hQCT90:02"]
    loaded = ImportedState.load(path)
    assert "instagram:quinn.xyz:DYld7hQCT90:01" in loaded.records
    assert "instagram:quinn.xyz:DYld7hQCT90:02" not in loaded.records


def test_forget_dry_run_does_not_modify_file(project_tmp_path):
    path = project_tmp_path / "state" / "imported.json"
    write_state(path, sample_import_records())
    original = path.read_text(encoding="utf-8")
    state = ImportedState.load(path)

    result = state.forget(shortcode="DYld7hQCT90", dry_run=True)

    assert result.matched_count == 3
    assert result.removed_count == 0
    assert result.backup_path is None
    assert path.read_text(encoding="utf-8") == original


def test_forget_missing_record_is_clear_noop(project_tmp_path):
    path = project_tmp_path / "state" / "imported.json"
    write_state(path, sample_import_records())
    state = ImportedState.load(path)

    result = state.forget(shortcode="MISSING")

    assert result.matched_count == 0
    assert result.removed_count == 0
    assert result.removed_keys == []
    assert result.backup_path is None
