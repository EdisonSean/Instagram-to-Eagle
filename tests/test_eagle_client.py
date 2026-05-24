import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from ins_eagle_sync.eagle_client import EagleApiError, EagleClient
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
    _, kwargs = post_mock.call_args
    assert kwargs["json"] == {
        "path": str(item.file_path),
        "name": item.title,
        "website": item.website,
        "annotation": item.annotation,
        "tags": item.tags,
        "folderId": "folder-1",
    }


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
