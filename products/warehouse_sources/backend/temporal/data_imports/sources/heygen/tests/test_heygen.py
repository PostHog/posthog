from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, Mock

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.heygen.heygen import (
    HeyGenResumeConfig,
    heygen_source,
    probe_endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.heygen.tests.utils import sync_items


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
    assert not manager.has_staged_state()
    assert next(pages) == [{"id": "video-last"}]
    manager.commit()
    saved = redis.set.call_args.args[1]
    assert saved == '{"cursor":"opaque+/=token"}'
    assert parse_qs(urlsplit(http.call_args.args[0].url).query)["token"] == ["opaque+/=token"]
    assert list(pages) == []
    redis.delete.assert_called_once()
    assert http.call_count == 2


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


@pytest.mark.parametrize("status", [400, 404])
def test_probe_does_not_classify_other_failures_as_bad_credentials(
    status: int, http: Mock, response: Callable[..., Response]
) -> None:
    http.return_value = response({"error": "invalid_request"}, status)
    with pytest.raises(HTTPError):
        probe_endpoint("fake-key", "videos", "v3")
    assert http.call_count == 1
