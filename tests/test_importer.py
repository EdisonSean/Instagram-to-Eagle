import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ins_eagle_sync.eagle_client import EagleApiError
from ins_eagle_sync.importer import import_staging_items
from ins_eagle_sync.metadata_parser import ImportItem
from ins_eagle_sync.state_store import ImportedState


class FakeEagle:
    def __init__(self, *, response=None, error=None):
        self.response = response or {"status": "success", "data": {"id": "eagle-item-1"}}
        self.error = error
        self.check_calls = 0
        self.add_calls = []

    def check_app_available(self):
        self.check_calls += 1
        return True

    def add_item_from_path(self, import_item, folder_id):
        self.add_calls.append((import_item, folder_id))
        if self.error is not None:
            raise self.error
        return self.response


def make_item(project_tmp_path, *, index=1):
    media_path = project_tmp_path / f"media_{index:02d}.jpg"
    media_path.write_bytes(b"fake image")
    return ImportItem(
        file_path=media_path,
        title=f"Caption ｜ ABC123_{index:02d}",
        website="https://www.instagram.com/p/ABC123/",
        annotation="作者: author\nCaption 全文:\nCaption",
        tags=["instagram", "author:author", "shortcode:ABC123"],
        unique_key=f"instagram:author:ABC123:{index:02d}",
        username="author",
        shortcode="ABC123",
        media_index=index,
    )


def test_dry_run_does_not_call_eagle_api(project_tmp_path):
    item = make_item(project_tmp_path)
    state = ImportedState.load(project_tmp_path / "state.json")
    eagle = FakeEagle()
    logs = []

    result = import_staging_items(
        [item],
        eagle=eagle,
        state=state,
        folder_id="folder-1",
        dry_run=True,
        log=logs.append,
    )

    assert result.total == 1
    assert result.imported == 0
    assert result.failed == 0
    assert eagle.check_calls == 0
    assert eagle.add_calls == []
    assert any(item.title in line for line in logs)
    assert not state.path.exists()


def test_existing_unique_key_is_skipped(project_tmp_path):
    item = make_item(project_tmp_path)
    state = ImportedState.load(project_tmp_path / "state.json")
    state.mark_item_imported(item, eagle_item_id="existing")
    eagle = FakeEagle()

    result = import_staging_items([item], eagle=eagle, state=state, folder_id="folder-1", log=lambda _line: None)

    assert result.skipped == 1
    assert result.imported == 0
    assert eagle.check_calls == 0
    assert eagle.add_calls == []


def test_force_does_not_skip_existing_unique_key(project_tmp_path):
    item = make_item(project_tmp_path)
    state = ImportedState.load(project_tmp_path / "state.json")
    state.mark_item_imported(item, eagle_item_id="existing")
    eagle = FakeEagle(response={"status": "success", "data": {"id": "new-id"}})

    result = import_staging_items(
        [item],
        eagle=eagle,
        state=state,
        folder_id="folder-1",
        force=True,
        log=lambda _line: None,
    )

    assert result.skipped == 0
    assert result.imported == 1
    assert eagle.check_calls == 1
    assert len(eagle.add_calls) == 1
    assert state.records[item.unique_key]["eagle_item_id"] == "new-id"


def test_successful_import_writes_imported_state(project_tmp_path):
    item = make_item(project_tmp_path)
    state_path = project_tmp_path / "imported.json"
    state = ImportedState.load(state_path)
    eagle = FakeEagle(response={"status": "success", "data": {"id": "eagle-123"}})

    result = import_staging_items([item], eagle=eagle, state=state, folder_id="folder-1", log=lambda _line: None)

    assert result.imported == 1
    loaded = ImportedState.load(state_path)
    assert loaded.has_unique_key(item.unique_key)
    record = loaded.records[item.unique_key]
    assert record["file_path"] == str(item.file_path)
    assert record["website"] == item.website
    assert record["title"] == item.title
    assert record["eagle_item_id"] == "eagle-123"
    assert record["imported_at"]


def test_eagle_api_failure_returns_clear_error(project_tmp_path):
    item = make_item(project_tmp_path)
    state = ImportedState.load(project_tmp_path / "state.json")
    eagle = FakeEagle(error=EagleApiError("Eagle API failed to add item from path: boom"))
    logs = []

    result = import_staging_items([item], eagle=eagle, state=state, folder_id="folder-1", log=logs.append)

    assert result.imported == 0
    assert result.failed == 1
    assert result.failures[0].unique_key == item.unique_key
    assert "boom" in result.failures[0].error
    assert any("failed:" in line and "boom" in line for line in logs)
    assert not state.path.exists()
