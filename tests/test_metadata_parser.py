import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ins_eagle_sync.metadata_parser import parse_metadata_item


def test_parse_metadata_item_normalizes_common_fields(tmp_path):
    metadata_path = tmp_path / "ABC123.json"
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
    assert result.local_file == tmp_path / "image.jpg"
    assert result.hashtags == ["tag"]
