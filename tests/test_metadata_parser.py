import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ins_eagle_sync.metadata_parser import (
    build_import_title,
    parse_metadata_item,
    scan_staging_dir,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_parse_metadata_item_normalizes_common_fields(project_tmp_path):
    metadata_path = project_tmp_path / "ABC123.json"
    item = {
        "shortcode": "ABC123",
        "num": 2,
        "description": "caption #Tag",
        "username": "author",
        "post_url": "https://www.instagram.com/p/ABC123/",
        "date": "2024-01-01",
        "filename": "image.jpg",
    }

    result = parse_metadata_item(item, metadata_path)

    assert result.shortcode == "ABC123"
    assert result.media_index == 2
    assert result.caption == "caption #Tag"
    assert result.author == "author"
    assert result.local_file == project_tmp_path / "image.jpg"
    assert result.hashtags == ["tag"]


def test_parse_metadata_item_normalizes_source_url_for_website_and_annotation(project_tmp_path):
    metadata_path = project_tmp_path / "ABC123.json"
    item = {
        "num": 1,
        "description": "caption",
        "username": "author",
        "post_url": "https://www.instagram.com/reel/ABC123/?igsh=abc#x",
        "filename": "video.mp4",
    }

    result = parse_metadata_item(item, metadata_path)

    assert result.shortcode == "ABC123"
    assert result.website == "https://www.instagram.com/reel/ABC123/"
    assert result.source_url == "https://www.instagram.com/reel/ABC123/"
    assert result.unique_key == "instagram:author:ABC123:01"
    assert "https://www.instagram.com/reel/ABC123/" in result.annotation


def test_parse_gallery_dl_instagram_fields_prefers_post_shortcode(project_tmp_path):
    metadata = json.loads((FIXTURES_DIR / "instagram_sidecar_item.json").read_text(encoding="utf-8"))
    file_path = project_tmp_path / "unknown" / "DYld7hQCT90" / "media_02.jpg"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"fake image")
    metadata_path = Path(str(file_path) + ".json")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    result = parse_metadata_item(
        metadata,
        metadata_path,
        file_path=file_path,
        staging_dir=project_tmp_path,
    )

    assert result.file_path == file_path
    assert result.username == "quinn.xyz"
    assert result.shortcode == "DYld7hQCT90"
    assert result.media_index == 2
    assert result.website == "https://www.instagram.com/p/DYld7hQCT90/"
    assert result.title == "A calm city walk #Travel #Night #travel"
    assert "DYld7hQCT90" not in result.title
    assert "_02" not in result.title
    assert result.unique_key == "instagram:quinn.xyz:DYld7hQCT90:02"
    assert result.tags == [
        "instagram",
        "author:quinn.xyz",
        "travel",
        "night",
    ]
    assert "shortcode:DYld7hQCT90" not in result.tags
    assert "作者: quinn.xyz" in result.annotation
    assert "日期: 2026-01-15 08:30:00" in result.annotation
    assert "Shortcode: DYld7hQCT90" in result.annotation
    assert "序号: 02" in result.annotation
    assert "来源 URL: https://www.instagram.com/p/DYld7hQCT90/" in result.annotation
    assert "Caption 全文:" in result.annotation
    assert "A calm city walk #Travel #Night #travel" in result.annotation


def test_scan_staging_dir_finds_media_and_matching_metadata(project_tmp_path):
    metadata = json.loads((FIXTURES_DIR / "instagram_sidecar_item.json").read_text(encoding="utf-8"))
    media_path = project_tmp_path / "unknown" / "DYld7hQCT90" / "media_02.jpg"
    media_path.parent.mkdir(parents=True)
    media_path.write_bytes(b"fake image")
    Path(str(media_path) + ".json").write_text(json.dumps(metadata), encoding="utf-8")
    (media_path.parent / "ignored.txt").write_text("ignore me", encoding="utf-8")

    items = scan_staging_dir(project_tmp_path)

    assert len(items) == 1
    assert items[0].file_path == media_path
    assert items[0].shortcode == "DYld7hQCT90"
    assert items[0].media_index == 2


def test_scan_staging_dir_sorts_by_shortcode_and_media_index(project_tmp_path):
    media_specs = [
        ("z_video.mp4", "ORDER1", 1),
        ("a_image.jpg", "ORDER1", 2),
        ("m_image.jpg", "ORDER1", 3),
    ]
    target_dir = project_tmp_path / "unknown" / "ORDER1"
    target_dir.mkdir(parents=True)

    for filename, shortcode, media_index in media_specs:
        media_path = target_dir / filename
        media_path.write_bytes(b"fake media")
        metadata = {
            "username": "author",
            "post_shortcode": shortcode,
            "description": f"caption {media_index}",
            "num": media_index,
        }
        Path(str(media_path) + ".json").write_text(json.dumps(metadata), encoding="utf-8")

    items = scan_staging_dir(project_tmp_path)

    assert [item.media_index for item in items] == [1, 2, 3]
    assert [item.unique_key for item in items] == [
        "instagram:author:ORDER1:01",
        "instagram:author:ORDER1:02",
        "instagram:author:ORDER1:03",
    ]


def test_scan_staging_dir_uses_path_fallbacks_without_metadata(project_tmp_path):
    media_path = project_tmp_path / "unknown" / "FALLBACK1" / "photo_03.mp4"
    media_path.parent.mkdir(parents=True)
    media_path.write_bytes(b"fake video")

    items = scan_staging_dir(project_tmp_path)

    assert len(items) == 1
    item = items[0]
    assert item.file_path == media_path
    assert item.username == "unknown"
    assert item.shortcode == "FALLBACK1"
    assert item.media_index == 3
    assert item.caption == ""
    assert item.title == "Instagram Post"
    assert item.website == "https://www.instagram.com/p/FALLBACK1/"
    assert item.unique_key == "instagram:unknown:FALLBACK1:03"
    assert item.tags == ["instagram", "author:unknown"]


def test_parse_metadata_item_supports_nested_user_and_title_fallback(project_tmp_path):
    item = {
        "profile": {"username": "nested.author"},
        "shortcode_id": "POST999",
        "title": "Title caption #Art",
        "datetime": "2026-02-03T04:05:06",
        "index": "4",
    }
    media_path = project_tmp_path / "nested" / "POST999" / "asset_04.webp"
    media_path.parent.mkdir(parents=True)
    media_path.write_bytes(b"fake image")

    result = parse_metadata_item(item, file_path=media_path, staging_dir=project_tmp_path)

    assert result.username == "nested.author"
    assert result.shortcode == "POST999"
    assert result.media_index == 4
    assert result.caption == "Title caption #Art"
    assert "art" in result.tags


def test_build_import_title_uses_author_when_caption_is_empty():
    assert build_import_title("", "quinn.xyz") == "quinn.xyz"


def test_build_import_title_uses_generic_title_when_caption_and_author_are_empty():
    assert build_import_title("", "unknown") == "Instagram Post"


def test_build_import_title_uses_configurable_caption_length():
    caption = "A" * 75

    assert build_import_title(caption, "author", caption_chars=70) == "A" * 70
