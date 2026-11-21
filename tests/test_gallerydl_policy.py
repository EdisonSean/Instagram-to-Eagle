from io import BytesIO
from unittest.mock import Mock

import pytest
from gallery_dl.exception import StopExtraction

from ins_eagle_sync import gallerydl_policy as policy


def test_page_budget_counts_requests_even_when_no_posts_are_yielded():
    guard = policy.InstagramRequestPolicy(BytesIO(), (8, 15), 2)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(policy.time, "sleep", lambda _delay: None)
        guard.before_request("https://www.instagram.com/web/search/topsearch/")
        guard.before_request("https://www.instagram.com/api/v1/feed/user/1/")
        guard.before_request("https://www.instagram.com/api/v1/feed/user/1/?max_id=2")
        with pytest.raises(StopExtraction):
            guard.before_request("https://www.instagram.com/api/v1/feed/user/1/?max_id=3")


@pytest.mark.parametrize(
    ("status", "headers", "payload"),
    [
        (429, {}, None),
        (403, {}, None),
        (302, {"Location": "/challenge/123/"}, None),
        (200, {"Content-Type": "application/json"}, {"message": "challenge_required"}),
    ],
)
def test_restriction_response_leaves_the_downloader_before_it_can_retry(status, headers, payload):
    response = Mock(status_code=status, url="https://www.instagram.com/api/item/", headers=headers)
    response.is_redirect = status == 302
    response.json.return_value = payload
    guard = policy.InstagramRequestPolicy(BytesIO(), (8, 15), 1)

    with pytest.raises(policy.InstagramRestricted) as caught:
        guard.check_response(response)

    assert caught.value.code == policy.RESTRICTED_EXIT_CODE
    assert not isinstance(caught.value, Exception)


def test_next_task_observes_previous_task_request_time(tmp_path, monkeypatch):
    clock_path = tmp_path / "instagram-request-clock"
    timestamp = 100.0
    delays = []

    def sleep(seconds):
        nonlocal timestamp
        delays.append(seconds)
        timestamp += seconds

    monkeypatch.setattr(policy.time, "monotonic", lambda: timestamp)
    monkeypatch.setattr(policy.time, "sleep", sleep)
    with policy.request_clock(clock_path) as clock:
        first_task = policy.InstagramRequestPolicy(clock, (8, 8), 2)
        first_task.before_request("https://www.instagram.com/api/item/")
    timestamp += 3
    with policy.request_clock(clock_path) as clock:
        login_test = policy.InstagramRequestPolicy(clock, (8, 8), 1)
        login_test.before_request("https://www.instagram.com/api/another-item/")

    assert delays == [5.0]
