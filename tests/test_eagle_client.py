import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest
import requests

from ins_eagle_sync.eagle_client import EagleApiError, EagleClient, extract_eagle_item_id
from ins_eagle_sync.metadata_parser import ImportItem


def make_response(status_code=200, payload=None, text=""):
    response = Mock()
    response.status_code = status_code
    response.text = text
    response.json.return_value = payload if payload is not None else {"status": "success", "data": {"id": "1"}}
    return response


def test_check_app_available_uses_application_info_endpoint():
    with patch("ins_eagle_sync.eagle_client.requests.get", return_value=make_response()) as get_mock:
        client = EagleClient("http://localhost:41595")

        assert client.check_app_available() is True

    get_mock.assert_called_once_with("http://localhost:41595/api/application/info", timeout=5)


def test_add_item_from_path_posts_import_item_payload(project_tmp_path):
    item = ImportItem(
        file_path=project_tmp_path / "image.jpg",
        title="Title ｜ ABC123_01",
        website="https://www.instagram.com/p/ABC123/",
        annotation="annotation",
        tags=["instagram"],
        unique_key="instagram:user:ABC123:01",
        username="user",
        shortcode="ABC123",
        media_index=1,
    )

    with patch("ins_eagle_sync.eagle_client.requests.post", return_value=make_response()) as post_mock:
        response = EagleClient("http://localhost:41595").add_item_from_path(item, "folder-1")

    assert response["status"] == "success"
    assert response["eagle_item_id"] == "1"
    _, kwargs = post_mock.call_args
    assert kwargs["json"] == {
        "path": str(item.file_path),
        "name": item.title,
        "website": item.website,
        "annotation": item.annotation,
        "tags": item.tags,
        "folderId": "folder-1",
    }


def test_add_item_from_path_recovers_id_from_item_list_when_response_has_no_id(project_tmp_path):
    item = ImportItem(
        file_path=project_tmp_path / "image.jpg",
        title="Title",
        website="https://www.instagram.com/p/ABC123/",
        annotation="Shortcode: ABC123\n序号: 01",
        tags=["instagram"],
        unique_key="instagram:user:ABC123:01",
        username="user",
        shortcode="ABC123",
        media_index=1,
    )
    add_response = make_response(payload={"status": "success"})
    list_response = make_response(
        payload={
            "status": "success",
            "data": [
                {
                    "id": "recovered-id",
                    "name": item.title,
                    "url": item.website,
                    "annotation": item.annotation,
                    "folders": ["folder-1"],
                    "isDeleted": False,
                }
            ],
        }
    )

    with (
        patch("ins_eagle_sync.eagle_client.requests.post", return_value=add_response),
        patch("ins_eagle_sync.eagle_client.requests.get", return_value=list_response) as get_mock,
    ):
        response = EagleClient("http://localhost:41595").add_item_from_path(item, "folder-1")

    assert response["eagle_item_id"] == "recovered-id"
    get_mock.assert_called_once_with(
        "http://localhost:41595/api/item/list",
        params={"limit": 200, "offset": 0, "orderBy": "-CREATEDATE", "folders": "folder-1"},
        timeout=10,
    )


def test_add_item_from_path_raises_clear_error_for_failed_response():
    response = make_response(
        status_code=500,
        payload={"status": "error", "message": "Eagle exploded"},
        text='{"status":"error"}',
    )

    with patch("ins_eagle_sync.eagle_client.requests.post", return_value=response):
        with pytest.raises(EagleApiError, match="HTTP 500.*Eagle exploded"):
            EagleClient("http://localhost:41595").add_item_from_path(
                ImportItem(
                    file_path=Path("image.jpg"),
                    title="Title",
                    website="https://www.instagram.com/p/ABC123/",
                    annotation="annotation",
                    tags=["instagram"],
                    unique_key="instagram:user:ABC123:01",
                    username="user",
                    shortcode="ABC123",
                    media_index=1,
                ),
                "folder-1",
            )


def test_item_exists_returns_true_when_not_deleted():
    response = make_response(payload={"status": "success", "data": {"id": "item-1", "isDeleted": False}})

    with patch("ins_eagle_sync.eagle_client.requests.get", return_value=response) as get_mock:
        assert EagleClient("http://localhost:41595").item_exists("item-1") is True

    get_mock.assert_called_once_with(
        "http://localhost:41595/api/item/info",
        params={"id": "item-1"},
        timeout=10,
    )


def test_item_exists_returns_false_when_deleted():
    response = make_response(payload={"status": "success", "data": {"id": "item-1", "isDeleted": True}})

    with patch("ins_eagle_sync.eagle_client.requests.get", return_value=response):
        assert EagleClient("http://localhost:41595").item_exists("item-1") is False


def test_item_exists_returns_false_when_item_is_not_found():
    response = make_response(
        status_code=404,
        payload={"status": "error", "message": "item not found"},
        text='{"status":"error"}',
    )

    with patch("ins_eagle_sync.eagle_client.requests.get", return_value=response):
        assert EagleClient("http://localhost:41595").item_exists("item-1") is False


def test_item_exists_returns_false_when_eagle_reports_file_does_not_exist_with_500():
    response = make_response(
        status_code=500,
        payload={"status": "error", "data": "File does not exist."},
        text='{"status":"error","data":"File does not exist."}',
    )

    with patch("ins_eagle_sync.eagle_client.requests.get", return_value=response):
        assert EagleClient("http://localhost:41595").item_exists("item-1") is False


def test_item_exists_raises_clear_error_on_unconfirmed_500():
    response = make_response(
        status_code=500,
        payload={"status": "error", "data": "Database is busy."},
        text='{"status":"error","data":"Database is busy."}',
    )

    with patch("ins_eagle_sync.eagle_client.requests.get", return_value=response):
        with pytest.raises(EagleApiError, match="HTTP 500.*Database is busy"):
            EagleClient("http://localhost:41595").item_exists("item-1")


def test_item_exists_raises_clear_error_on_api_failure():
    response = make_response(
        status_code=500,
        payload={"status": "error", "message": "missing"},
        text='{"status":"error"}',
    )

    with patch("ins_eagle_sync.eagle_client.requests.get", return_value=response):
        with pytest.raises(EagleApiError, match="HTTP 500.*missing"):
            EagleClient("http://localhost:41595").item_exists("item-1")


def test_get_item_info_raises_clear_error_on_connection_failure():
    with patch(
        "ins_eagle_sync.eagle_client.requests.get",
        side_effect=requests.RequestException("connection refused"),
    ):
        with pytest.raises(EagleApiError, match="item info request failed.*connection refused"):
            EagleClient("http://localhost:41595").get_item_info("item-1")


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"status": "success", "data": {"id": "item-1"}}, "item-1"),
        ({"status": "success", "eagle_item_id": "item-0"}, "item-0"),
        ({"status": "success", "data": {"itemId": "item-2"}}, "item-2"),
        ({"status": "success", "data": {"item_id": "item-3"}}, "item-3"),
        ({"status": "success", "data": "item-4"}, "item-4"),
        ({"status": "success", "data": {"item": {"id": "item-5"}}}, "item-5"),
        ({"status": "success", "data": {"items": [{"id": "item-6"}]}}, "item-6"),
        ({"status": "success", "id": "item-7"}, "item-7"),
    ],
)
def test_extract_eagle_item_id_supports_common_response_shapes(payload, expected):
    assert extract_eagle_item_id(payload) == expected
