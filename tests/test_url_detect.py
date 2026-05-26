import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from ins_eagle_sync.utils import (
    InstagramMode,
    detect_instagram_url,
    normalize_instagram_post_urls,
    normalize_instagram_url,
    split_instagram_url_text,
)


def test_detect_author_url_with_dot_username():
    result = detect_instagram_url("https://www.instagram.com/quinn.xyz/")

    assert result.mode == InstagramMode.AUTHOR
    assert result.username == "quinn.xyz"
    assert result.normalized_url == "https://www.instagram.com/quinn.xyz/"


def test_detect_post_url():
    result = detect_instagram_url("https://www.instagram.com/p/DYld7hQCT90/?img_index=1#comments")

    assert result.mode == InstagramMode.POST
    assert result.shortcode == "DYld7hQCT90"
    assert result.normalized_url == "https://www.instagram.com/p/DYld7hQCT90/"


def test_detect_reel_url_as_post():
    result = detect_instagram_url("https://www.instagram.com/reel/DYld7hQCT90/")

    assert result.mode == InstagramMode.POST
    assert result.shortcode == "DYld7hQCT90"
    assert result.normalized_url == "https://www.instagram.com/reel/DYld7hQCT90/"


def test_detect_tv_url_as_post():
    result = detect_instagram_url("https://www.instagram.com/tv/DYld7hQCT90/?utm_source=ig_web_copy_link")

    assert result.mode == InstagramMode.POST
    assert result.shortcode == "DYld7hQCT90"
    assert result.normalized_url == "https://www.instagram.com/tv/DYld7hQCT90/"


def test_normalize_instagram_url_removes_query_and_fragment():
    assert (
        normalize_instagram_url("https://www.instagram.com/p/DPCujtjEowk/?img_index=1#comments")
        == "https://www.instagram.com/p/DPCujtjEowk/"
    )


def test_split_instagram_url_text_accepts_common_user_separators():
    text = """
    https://www.instagram.com/p/ABC123/?img_index=1
    https://www.instagram.com/reel/DEF456/，https://www.instagram.com/tv/GHI789/;
    """

    assert split_instagram_url_text(text) == [
        "https://www.instagram.com/p/ABC123/?img_index=1",
        "https://www.instagram.com/reel/DEF456/",
        "https://www.instagram.com/tv/GHI789/",
    ]


def test_normalize_instagram_post_urls_deduplicates_and_rejects_authors():
    text = "https://www.instagram.com/p/ABC123/?x=1 https://www.instagram.com/p/ABC123/"

    assert normalize_instagram_post_urls(text) == ["https://www.instagram.com/p/ABC123/"]

    with pytest.raises(ValueError, match="Single-post mode"):
        normalize_instagram_post_urls("https://www.instagram.com/quinn.xyz/")


def test_detect_stories_url_as_unsupported():
    with pytest.raises(ValueError, match="Unsupported Instagram URL"):
        detect_instagram_url("https://www.instagram.com/stories/quinn.xyz/123456/")
