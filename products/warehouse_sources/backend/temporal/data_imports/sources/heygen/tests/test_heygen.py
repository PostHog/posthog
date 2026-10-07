from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, Mock, patch

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.heygen.heygen import (
    HeyGenResumeConfig,
    heygen_source,
    probe_endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.heygen.tests.utils import sync_items


@pytest.mark.parametrize(
    "endpoint,path,key,params,row",
    [
        ("videos", "videos", "id", {"limit": ["100"]}, {"id": "video-test", "created_at": 1780000000}),
        ("video_translations", "video-translations", "id", {"limit": ["100"]}, {"id": "translation-test"}),
        ("video_agent_sessions", "video-agents", "session_id", {"limit": ["100"]}, {"session_id": "session-test"}),
        ("avatar_groups", "avatars", "id", {"limit": ["50"], "ownership": ["private"]}, {"id": "group-test"}),
        ("avatar_looks", "avatars/looks", "id", {"limit": ["50"], "ownership": ["private"]}, {"id": "look-test"}),
        ("voices", "voices", "voice_id", {"limit": ["100"], "type": ["private"]}, {"voice_id": "voice-test"}),
        ("templates", "templates", "id", {"limit": ["100"]}, {"id": "template-test"}),
        ("account", "users/me", "username", {}, {"username": "user-test", "wallet": {"remaining_balance": 25}}),
    ],
)
def test_endpoint_requests_and_rows(
    endpoint: str,
    path: str,
    key: str,
    params: dict[str, list[str]],
    row: dict[str, Any],
    http: Mock,
    response: Callable[..., Response],
    manager: ResumableSourceManager[HeyGenResumeConfig],
) -> None:
    http.return_value = response(
        {"data": row if endpoint == "account" else [row], "next_token": None, "has_more": False}
    )
    source = heygen_source("fake-heygen-key", endpoint, "v3", 1, "job-test", manager)

    assert list(sync_items(source)) == [[row]]
    request = http.call_args.args[0]
    assert urlsplit(request.url).path == f"/v3/{path}"
    assert parse_qs(urlsplit(request.url).query) == params
    assert request.headers["x-api-key"] == "fake-heygen-key"
    assert http.call_args.kwargs["allow_redirects"] is False
    assert source.primary_keys == [key]
    if endpoint == "videos":
        assert source.partition_keys == ["created_at"]


@pytest.mark.parametrize("terminal_token", [None, ""])
def test_cursor_pages_checkpoint_after_yield(
    terminal_token: str | None,
    http: Mock,
    response: Callable[..., Response],
    manager: ResumableSourceManager[HeyGenResumeConfig],
    redis: MagicMock,
) -> None:
    http.side_effect = [
        response({"data": [{"id": "video-first"}], "has_more": True, "next_token": "opaque+/=token"}),
        response({"data": [{"id": "video-last"}], "has_more": False, "next_token": terminal_token}),
    ]
    pages = iter(sync_items(heygen_source("fake-key", "videos", "v3", 1, "job-test", manager)))
    assert next(pages) == [{"id": "video-first"}]
    manager.confirm()
    assert not manager.has_staged_state()
    assert next(pages) == [{"id": "video-last"}]
    manager.confirm()
    manager.commit()
    saved = redis.set.call_args.args[1]
    assert saved == '{"cursor":"opaque+/=token"}'
    assert parse_qs(urlsplit(http.call_args.args[0].url).query)["token"] == ["opaque+/=token"]
    assert list(pages) == []
    redis.delete.assert_called_once()
    assert http.call_count == 2


def test_resume_uses_saved_cursor(
    http: Mock,
    response: Callable[..., Response],
    manager: ResumableSourceManager[HeyGenResumeConfig],
    redis: MagicMock,
) -> None:
    redis.exists.return_value = 1
    redis.get.return_value = b'{"cursor":"saved-token"}'
    http.return_value = response({"data": [{"id": "remaining-video"}], "next_token": None, "has_more": False})
    assert list(sync_items(heygen_source("fake-key", "videos", "v3", 1, "job-test", manager))) == [
        [{"id": "remaining-video"}]
    ]
    assert parse_qs(urlsplit(http.call_args.args[0].url).query) == {"limit": ["100"], "token": ["saved-token"]}


def test_account_ignores_saved_list_cursor(
    http: Mock,
    response: Callable[..., Response],
    manager: ResumableSourceManager[HeyGenResumeConfig],
    redis: MagicMock,
) -> None:
    redis.exists.return_value = 1
    redis.get.return_value = b'{"cursor":"saved-token"}'
    http.return_value = response({"data": {"username": "user-test", "subscription": {"credits": {"remaining": 2}}}})
    source = heygen_source("fake-key", "account", "v3", 1, "job-test", manager)
    assert next(iter(sync_items(source)))[0]["subscription"]["credits"]["remaining"] == 2
    assert not source.supports_resume
    assert not urlsplit(http.call_args.args[0].url).query
    redis.get.assert_not_called()


def test_empty_list_is_valid_but_missing_data_fails(
    http: Mock, response: Callable[..., Response], manager: ResumableSourceManager[HeyGenResumeConfig]
) -> None:
    http.return_value = response({"data": [], "has_more": False, "next_token": None})
    assert list(sync_items(heygen_source("fake-key", "videos", "v3", 1, "job-test", manager))) == []
    http.return_value = response({"unexpected": []})
    with pytest.raises(ValueError, match="matched nothing"):
        list(sync_items(heygen_source("fake-key", "videos", "v3", 1, "job-test", manager)))


@pytest.mark.parametrize("status", [200, 401, 403])
def test_probe_auth_status_and_single_request(status: int, http: Mock, response: Callable[..., Response]) -> None:
    http.return_value = response({"data": [], "has_more": True, "next_token": "more"}, status)
    assert probe_endpoint("fake-key", "videos", "v3") == status
    assert parse_qs(urlsplit(http.call_args.args[0].url).query) == {"limit": ["1"]}
    assert http.call_count == 1


@pytest.mark.parametrize("status", [400, 404])
def test_probe_does_not_classify_other_failures_as_bad_credentials(
    status: int, http: Mock, response: Callable[..., Response]
) -> None:
    http.return_value = response({"error": "invalid_request"}, status)
    with pytest.raises(HTTPError):
        probe_endpoint("fake-key", "videos", "v3")
    assert http.call_count == 1


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_transport_retries_and_honors_retry_after(
    status: int,
    http: Mock,
    response: Callable[..., Response],
    manager: ResumableSourceManager[HeyGenResumeConfig],
) -> None:
    failure = response({"error": "temporarily_unavailable"}, status)
    failure.headers["Retry-After"] = "2"
    http.side_effect = [failure, response({"data": [{"id": "video-test"}], "next_token": None})]
    with patch("tenacity.nap.time.sleep") as sleep:
        assert list(sync_items(heygen_source("fake-key", "videos", "v3", 1, "job-test", manager))) == [
            [{"id": "video-test"}]
        ]
    assert http.call_count == 2
    sleep.assert_called_once_with(2)
