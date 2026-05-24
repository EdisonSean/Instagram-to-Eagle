import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ins_eagle_sync.utils import build_eagle_title, extract_hashtags


def test_build_eagle_title_truncates_caption():
    title = build_eagle_title("这是一个很长很长的 caption 文本", "ABC123", 2, caption_chars=5)

    assert title == "这是一个很 - ABC123 - 2"


def test_build_eagle_title_handles_empty_caption():
    title = build_eagle_title("", "ABC123", 1)

    assert title == "ABC123 - 1"


def test_extract_hashtags_deduplicates_lowercase():
    tags = extract_hashtags("Hello #Travel #travel #上海")

    assert tags == ["travel", "上海"]
