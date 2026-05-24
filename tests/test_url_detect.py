import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from ins_eagle_sync.utils import InstagramMode, detect_instagram_url


def test_detect_author_url_with_dot_username():
    result = detect_instagram_url("https://www.instagram.com/quinn.xyz/")

    assert result.mode == InstagramMode.AUTHOR
    assert result.username == "quinn.xyz"
    assert result.normalized_url == "https://www.instagram.com/quinn.xyz/"


def test_detect_post_url():
    result = detect_instagram_url("https://www.instagram.com/p/DYld7hQCT90/")

    assert result.mode == InstagramMode.POST
    assert result.shortcode == "DYld7hQCT90"
    assert result.normalized_url == "https://www.instagram.com/p/DYld7hQCT90/"


def test_detect_reel_url_as_post():
    result = detect_instagram_url("https://www.instagram.com/reel/DYld7hQCT90/")

    assert result.mode == InstagramMode.POST
    assert result.shortcode == "DYld7hQCT90"
    assert result.normalized_url == "https://www.instagram.com/reel/DYld7hQCT90/"


def test_detect_stories_url_as_unsupported():
    with pytest.raises(ValueError, match="Unsupported Instagram URL"):
        detect_instagram_url("https://www.instagram.com/stories/quinn.xyz/123456/")
