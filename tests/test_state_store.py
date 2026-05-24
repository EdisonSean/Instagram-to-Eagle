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
            "title": "Title ｜ ABC123_01",
        },
    )()

    state.mark_item_imported(item, eagle_item_id="eagle-1", imported_at="2026-01-01T00:00:00+00:00")
    state.save()

    loaded = ImportedState.load(path)
    assert loaded.has_unique_key("instagram:user:ABC123:01")
    assert loaded.records["instagram:user:ABC123:01"] == {
        "file_path": "image.jpg",
        "website": "https://www.instagram.com/p/ABC123/",
        "title": "Title ｜ ABC123_01",
        "eagle_item_id": "eagle-1",
        "imported_at": "2026-01-01T00:00:00+00:00",
    }
