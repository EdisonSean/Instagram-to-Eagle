import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ins_eagle_sync.eagle_client import EagleApiError, EagleClient
from ins_eagle_sync.importer import import_staging_items, verify_import_records
from ins_eagle_sync.metadata_parser import ImportItem
from ins_eagle_sync.state_store import ImportedState


def make_response(status_code=200, payload=None, text=""):
    response = Mock()
    response.status_code = status_code
    response.text = text
    response.json.return_value = payload if payload is not None else {"status": "success", "data": {"id": "1"}}
    return response


class FakeEagle:
    def __init__(
        self,
        *,
        response=None,
        error=None,
        existing_item_ids=None,
        item_exists_error=None,
        matching_item_id="",
        find_error=None,
    ):
        self.response = response or {"status": "success", "data": {"id": "eagle-item-1"}}
        self.error = error
        self.existing_item_ids = set(existing_item_ids or [])
        self.item_exists_error = item_exists_error
        self.matching_item_id = matching_item_id
        self.find_error = find_error
        self.check_calls = 0
        self.add_calls = []
        self.item_exists_calls = []
        self.find_calls = []

    def check_app_available(self):
        self.check_calls += 1
        return True

    def add_item_from_path(self, import_item, folder_id):
        self.add_calls.append((import_item, folder_id))
        if self.error is not None:
            raise self.error
        return self.response

    def item_exists(self, item_id):
        self.item_exists_calls.append(item_id)
        if self.item_exists_error is not None:
            raise self.item_exists_error
        return item_id in self.existing_item_ids

    def find_matching_item_id(self, import_item, folder_id):
        self.find_calls.append((import_item, folder_id))
        if self.find_error is not None:
            raise self.find_error
        return self.matching_item_id


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


def test_existing_unique_key_with_verify_eagle_alive_is_skipped(project_tmp_path):
    item = make_item(project_tmp_path)
    state = ImportedState.load(project_tmp_path / "state.json")
    state.mark_item_imported(item, eagle_item_id="existing")
    eagle = FakeEagle(existing_item_ids={"existing"})

    result = import_staging_items(
        [item],
        eagle=eagle,
        state=state,
        folder_id="folder-1",
        verify_eagle=True,
        log=lambda _line: None,
    )

    assert result.skipped == 1
    assert result.imported == 0
    assert eagle.item_exists_calls == ["existing"]
    assert eagle.check_calls == 0
    assert eagle.add_calls == []


def test_existing_unique_key_with_verify_eagle_missing_is_reimported(project_tmp_path):
    item = make_item(project_tmp_path)
    state_path = project_tmp_path / "state.json"
    state = ImportedState.load(state_path)
    state.mark_item_imported(item, eagle_item_id="missing")
    state.save()
    eagle = FakeEagle(response={"status": "success", "data": {"id": "replacement"}})

    result = import_staging_items(
        [item],
        eagle=eagle,
        state=state,
        folder_id="folder-1",
        verify_eagle=True,
        log=lambda _line: None,
    )

    assert result.skipped == 0
    assert result.imported == 1
    assert eagle.item_exists_calls == ["missing"]
    assert len(eagle.add_calls) == 1
    loaded = ImportedState.load(state_path)
    assert loaded.records[item.unique_key]["eagle_item_id"] == "replacement"


def test_existing_unique_key_with_verify_eagle_unknown_is_skipped(project_tmp_path):
    item = make_item(project_tmp_path)
    state_path = project_tmp_path / "state.json"
    state = ImportedState.load(state_path)
    state.mark_item_imported(item, eagle_item_id="existing")
    state.save()
    eagle = FakeEagle(item_exists_error=EagleApiError("connection refused"))
    logs = []

    result = import_staging_items(
        [item],
        eagle=eagle,
        state=state,
        folder_id="folder-1",
        verify_eagle=True,
        log=logs.append,
    )

    assert result.skipped == 1
    assert result.imported == 0
    assert result.failed == 0
    assert eagle.item_exists_calls == ["existing"]
    assert eagle.check_calls == 0
    assert eagle.add_calls == []
    loaded = ImportedState.load(state_path)
    assert loaded.records[item.unique_key]["eagle_item_id"] == "existing"
    assert any("warning: could not verify Eagle item existing" in line for line in logs)


def test_existing_unique_key_without_id_recovers_id_and_skips(project_tmp_path):
    item = make_item(project_tmp_path)
    state_path = project_tmp_path / "state.json"
    state = ImportedState.load(state_path)
    state.mark_item_imported(item, eagle_item_id="")
    state.save()
    eagle = FakeEagle(matching_item_id="recovered-id")

    result = import_staging_items(
        [item],
        eagle=eagle,
        state=state,
        folder_id="folder-1",
        verify_eagle=True,
        log=lambda _line: None,
    )

    assert result.skipped == 1
    assert result.imported == 0
    assert eagle.find_calls == [(item, "folder-1")]
    assert eagle.check_calls == 0
    assert eagle.add_calls == []
    loaded = ImportedState.load(state_path)
    assert loaded.records[item.unique_key]["eagle_item_id"] == "recovered-id"


def test_existing_unique_key_without_id_reimports_when_no_matching_eagle_item(project_tmp_path):
    item = make_item(project_tmp_path)
    state_path = project_tmp_path / "state.json"
    state = ImportedState.load(state_path)
    state.mark_item_imported(item, eagle_item_id="")
    state.save()
    eagle = FakeEagle(response={"status": "success", "data": {"id": "replacement"}})

    result = import_staging_items(
        [item],
        eagle=eagle,
        state=state,
        folder_id="folder-1",
        verify_eagle=True,
        log=lambda _line: None,
    )

    assert result.skipped == 0
    assert result.imported == 1
    assert eagle.find_calls == [(item, "folder-1")]
    assert len(eagle.add_calls) == 1
    loaded = ImportedState.load(state_path)
    assert loaded.records[item.unique_key]["eagle_item_id"] == "replacement"


def test_existing_unique_key_without_id_unknown_search_is_skipped(project_tmp_path):
    item = make_item(project_tmp_path)
    state_path = project_tmp_path / "state.json"
    state = ImportedState.load(state_path)
    state.mark_item_imported(item, eagle_item_id="")
    state.save()
    eagle = FakeEagle(find_error=EagleApiError("connection refused"))

    result = import_staging_items(
        [item],
        eagle=eagle,
        state=state,
        folder_id="folder-1",
        verify_eagle=True,
        log=lambda _line: None,
    )

    assert result.skipped == 1
    assert result.imported == 0
    assert eagle.check_calls == 0
    assert eagle.add_calls == []
    loaded = ImportedState.load(state_path)
    assert loaded.records[item.unique_key]["eagle_item_id"] == ""


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


def test_successful_import_writes_eagle_item_id_from_nested_response(project_tmp_path):
    item = make_item(project_tmp_path)
    state_path = project_tmp_path / "imported.json"
    state = ImportedState.load(state_path)
    eagle = FakeEagle(response={"status": "success", "data": {"item": {"id": "nested-id"}}})

    result = import_staging_items([item], eagle=eagle, state=state, folder_id="folder-1", log=lambda _line: None)

    assert result.imported == 1
    loaded = ImportedState.load(state_path)
    assert loaded.records[item.unique_key]["eagle_item_id"] == "nested-id"


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


def test_verify_import_records_dry_run_does_not_modify_state(project_tmp_path):
    item = make_item(project_tmp_path)
    state_path = project_tmp_path / "state.json"
    state = ImportedState.load(state_path)
    state.mark_item_imported(item, eagle_item_id="missing")
    state.save()
    eagle = FakeEagle()

    result = verify_import_records(eagle=eagle, state=state, dry_run=True, log=lambda _line: None)

    assert result.checked == 1
    assert result.alive == 0
    assert result.missing == 1
    assert result.removed == 0
    assert ImportedState.load(state_path).has_unique_key(item.unique_key)


def test_verify_import_records_dry_run_treats_file_does_not_exist_as_missing(project_tmp_path):
    items = [make_item(project_tmp_path, index=index) for index in (1, 2, 3)]
    state_path = project_tmp_path / "state.json"
    state = ImportedState.load(state_path)
    for item in items:
        state.mark_item_imported(item, eagle_item_id=f"eagle-{item.media_index}")
    state.save()
    response = make_response(
        status_code=500,
        payload={"status": "error", "data": "File does not exist."},
        text='{"status":"error","data":"File does not exist."}',
    )

    with patch("ins_eagle_sync.eagle_client.requests.get", return_value=response):
        result = verify_import_records(
            eagle=EagleClient("http://localhost:41595"),
            state=state,
            shortcode="ABC123",
            dry_run=True,
            log=lambda _line: None,
        )

    assert result.checked == 3
    assert result.alive == 0
    assert result.missing == 3
    assert result.unknown == 0
    assert result.removed == 0
    loaded = ImportedState.load(state_path)
    assert all(loaded.has_unique_key(item.unique_key) for item in items)


def test_verify_import_records_removes_missing_state(project_tmp_path):
    item = make_item(project_tmp_path)
    state_path = project_tmp_path / "state.json"
    state = ImportedState.load(state_path)
    state.mark_item_imported(item, eagle_item_id="missing")
    state.save()
    eagle = FakeEagle()

    result = verify_import_records(eagle=eagle, state=state, log=lambda _line: None)

    assert result.checked == 1
    assert result.missing == 1
    assert result.removed == 1
    assert not ImportedState.load(state_path).has_unique_key(item.unique_key)


def test_verify_import_records_removes_file_does_not_exist_state(project_tmp_path):
    items = [make_item(project_tmp_path, index=index) for index in (1, 2, 3)]
    state_path = project_tmp_path / "state.json"
    state = ImportedState.load(state_path)
    for item in items:
        state.mark_item_imported(item, eagle_item_id=f"eagle-{item.media_index}")
    state.save()
    response = make_response(
        status_code=500,
        payload={"status": "error", "data": "File does not exist."},
        text='{"status":"error","data":"File does not exist."}',
    )

    with patch("ins_eagle_sync.eagle_client.requests.get", return_value=response):
        result = verify_import_records(
            eagle=EagleClient("http://localhost:41595"),
            state=state,
            shortcode="ABC123",
            log=lambda _line: None,
        )

    assert result.checked == 3
    assert result.missing == 3
    assert result.unknown == 0
    assert result.removed == 3
    loaded = ImportedState.load(state_path)
    assert all(not loaded.has_unique_key(item.unique_key) for item in items)


def test_verify_import_records_keeps_unconfirmed_500_as_unknown(project_tmp_path):
    item = make_item(project_tmp_path)
    state_path = project_tmp_path / "state.json"
    state = ImportedState.load(state_path)
    state.mark_item_imported(item, eagle_item_id="eagle-1")
    state.save()
    response = make_response(
        status_code=500,
        payload={"status": "error", "data": "Database is busy."},
        text='{"status":"error","data":"Database is busy."}',
    )

    with patch("ins_eagle_sync.eagle_client.requests.get", return_value=response):
        result = verify_import_records(
            eagle=EagleClient("http://localhost:41595"),
            state=state,
            dry_run=True,
            log=lambda _line: None,
        )

    assert result.checked == 1
    assert result.missing == 0
    assert result.unknown == 1
    assert result.removed == 0
    assert ImportedState.load(state_path).has_unique_key(item.unique_key)


def test_import_staging_verify_eagle_reimports_file_does_not_exist(project_tmp_path):
    item = make_item(project_tmp_path)
    state_path = project_tmp_path / "state.json"
    state = ImportedState.load(state_path)
    state.mark_item_imported(item, eagle_item_id="eagle-1")
    state.save()
    missing_response = make_response(
        status_code=500,
        payload={"status": "error", "data": "File does not exist."},
        text='{"status":"error","data":"File does not exist."}',
    )
    app_response = make_response(payload={"status": "success", "data": {"version": "1.0"}})
    add_response = make_response(payload={"status": "success", "data": {"id": "replacement"}})

    with (
        patch("ins_eagle_sync.eagle_client.requests.get", side_effect=[missing_response, app_response]),
        patch("ins_eagle_sync.eagle_client.requests.post", return_value=add_response),
    ):
        result = import_staging_items(
            [item],
            eagle=EagleClient("http://localhost:41595"),
            state=state,
            folder_id="folder-1",
            verify_eagle=True,
            log=lambda _line: None,
        )

    assert result.skipped == 0
    assert result.imported == 1
    loaded = ImportedState.load(state_path)
    assert loaded.records[item.unique_key]["eagle_item_id"] == "replacement"
