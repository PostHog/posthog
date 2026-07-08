from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.blogger import blogger
from products.warehouse_sources.backend.temporal.data_imports.sources.blogger.blogger import (
    BloggerResumeConfig,
    _build_params,
    _format_rfc3339,
    blogger_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.blogger.settings import BLOGGER_ENDPOINTS


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        json_data: dict | None = None,
        *,
        url: str = "https://www.googleapis.com/blogger/v3",
        reason: str = "OK",
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text
        self.url = url
        self.reason = reason
        self.ok = 200 <= status_code < 300

    def json(self) -> dict:
        return self._json

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(
                f"{self.status_code} error for url: {self.url}", response=cast(requests.Response, self)
            )


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.requested_urls: list[str] = []

    def get(self, url: str, headers: dict | None = None, timeout: int | None = None) -> _FakeResponse:
        self.requested_urls.append(url)
        return self._response


class _FakeResumableManager:
    def __init__(self, state: BloggerResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[BloggerResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> BloggerResumeConfig | None:
        return self._state

    def save_state(self, data: BloggerResumeConfig) -> None:
        self.saved.append(data)


class _SequentialFetch:
    """Stand-in for `_fetch_page` that returns canned responses in order and records request URLs."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.urls: list[str] = []

    def __call__(self, session: Any, url: str, headers: dict, logger: Any) -> dict:
        self.urls.append(url)
        return self._responses.pop(0)


def _collect(
    endpoint: str,
    manager: _FakeResumableManager,
    fetch: _SequentialFetch,
    **kwargs: Any,
) -> list[dict]:
    rows: list[dict] = []
    with (
        patch.object(blogger, "_fetch_page", fetch),
        patch.object(blogger, "make_tracked_session", lambda **_: MagicMock()),
    ):
        for batch in get_rows(
            api_key="K",
            blog_id="BID",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **kwargs,
        ):
            rows.extend(batch)
    return rows


class TestFormatRfc3339:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            (
                "non_utc_converted",
                datetime(2026, 3, 4, 2, 58, 14, tzinfo=timezone(timedelta(hours=2))),
                "2026-03-04T00:58:14Z",
            ),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "opaque-cursor", "opaque-cursor"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        assert _format_rfc3339(value) == expected

    def test_no_plus_zero_offset(self) -> None:
        assert "+00:00" not in _format_rfc3339(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


class TestBuildParams:
    def test_single_object_sends_only_key(self) -> None:
        params = _build_params(BLOGGER_ENDPOINTS["blogs"], "K", page_token=None, start_date=None)
        assert params == {"key": "K"}

    def test_posts_sends_max_results_and_order_by(self) -> None:
        params = _build_params(BLOGGER_ENDPOINTS["posts"], "K", page_token=None, start_date=None)
        assert params["key"] == "K"
        assert params["maxResults"] == 100
        assert params["orderBy"] == "published"
        assert "startDate" not in params
        assert "pageToken" not in params

    def test_comments_has_no_order_by(self) -> None:
        # comments.listByBlog rejects ordering params, so we never send orderBy for it.
        params = _build_params(BLOGGER_ENDPOINTS["comments"], "K", page_token=None, start_date=None)
        assert "orderBy" not in params

    def test_start_date_and_page_token_included(self) -> None:
        params = _build_params(BLOGGER_ENDPOINTS["posts"], "K", page_token="TOK", start_date="2026-03-04T00:00:00Z")
        assert params["startDate"] == "2026-03-04T00:00:00Z"
        assert params["pageToken"] == "TOK"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("bad_request", 400, False),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("not_found", 404, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_ok: bool) -> None:
        session = _FakeSession(_FakeResponse(status))
        with patch.object(blogger, "make_tracked_session", lambda **_: session):
            ok, error = validate_credentials("K", "BID")
        assert ok is expected_ok
        if not expected_ok:
            assert error

    def test_network_error_returns_false(self) -> None:
        class _Boom:
            def get(self, *args: Any, **kwargs: Any) -> Any:
                raise requests.ConnectionError("boom")

        with patch.object(blogger, "make_tracked_session", lambda **_: _Boom()):
            ok, error = validate_credentials("K", "BID")
        assert ok is False
        assert error


class TestGetRows:
    def test_single_object_yields_one_row(self) -> None:
        fetch = _SequentialFetch([{"id": "B1", "name": "My blog"}])
        manager = _FakeResumableManager()
        rows = _collect("blogs", manager, fetch)
        assert rows == [{"id": "B1", "name": "My blog"}]
        assert manager.saved == []
        assert "/blogs/BID?key=K" in fetch.urls[0]

    def test_list_paginates_and_saves_state_only_when_more_pages(self) -> None:
        fetch = _SequentialFetch(
            [
                {"items": [{"id": "p1"}, {"id": "p2"}], "nextPageToken": "T2"},
                {"items": [{"id": "p3"}], "nextPageToken": None},
            ]
        )
        manager = _FakeResumableManager()
        rows = _collect("posts", manager, fetch)
        assert [r["id"] for r in rows] == ["p1", "p2", "p3"]
        # State is saved once — after the first page (which had a next token), not after the last.
        assert manager.saved == [BloggerResumeConfig(page_token="T2")]
        # The second request carries the page token from the first response.
        assert "pageToken=T2" in fetch.urls[1]
        # Full refresh sends no startDate.
        assert all("startDate" not in url for url in fetch.urls)

    def test_incremental_maps_last_value_to_start_date(self) -> None:
        fetch = _SequentialFetch([{"items": [{"id": "p1"}], "nextPageToken": None}])
        manager = _FakeResumableManager()
        _collect(
            "posts",
            manager,
            fetch,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="published",
        )
        # Colons are percent-encoded by urlencode.
        assert "startDate=2026-03-04T02%3A58%3A14Z" in fetch.urls[0]

    def test_first_sync_without_last_value_sends_no_start_date(self) -> None:
        fetch = _SequentialFetch([{"items": [{"id": "p1"}], "nextPageToken": None}])
        manager = _FakeResumableManager()
        _collect(
            "posts",
            manager,
            fetch,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="published",
        )
        assert "startDate" not in fetch.urls[0]

    def test_resume_starts_from_saved_page_token(self) -> None:
        fetch = _SequentialFetch([{"items": [{"id": "p9"}], "nextPageToken": None}])
        manager = _FakeResumableManager(BloggerResumeConfig(page_token="RESUME"))
        rows = _collect("posts", manager, fetch)
        assert [r["id"] for r in rows] == ["p9"]
        assert "pageToken=RESUME" in fetch.urls[0]

    @parameterized.expand(
        [
            # Stop-immediately: a single empty page with no continuation token.
            ("single_empty_page", [{"items": [], "nextPageToken": None}], 1),
            # Walk-through: an empty page that still hands back a token loops to the next page,
            # which is also empty. No state is ever saved for empty pages.
            (
                "empty_pages_with_continuation",
                [{"items": [], "nextPageToken": "T2"}, {"items": [], "nextPageToken": None}],
                2,
            ),
        ]
    )
    def test_empty_items_never_save_state(self, _name: str, responses: list[dict], expected_requests: int) -> None:
        fetch = _SequentialFetch(responses)
        manager = _FakeResumableManager()
        rows = _collect("posts", manager, fetch)
        assert rows == []
        # Empty pages never persist a resume token: a crash mid-sequence re-walks the empty pages
        # rather than skipping past them, so no unseen data is missed on resume.
        assert manager.saved == []
        assert len(fetch.urls) == expected_requests
        if expected_requests > 1:
            # The continuation token from the empty page still drives the follow-up request.
            assert "pageToken=T2" in fetch.urls[1]


class TestFetchPageErrorSanitization:
    def test_client_error_strips_api_key_but_keeps_matchable_prefix(self) -> None:
        # The real URL carries the key in the query string; the raised error must not leak it.
        leaky_url = "https://www.googleapis.com/blogger/v3/blogs/BID/posts?key=SECRETKEY&maxResults=100"
        session = _FakeSession(_FakeResponse(400, url=leaky_url, reason="Bad Request"))
        with pytest.raises(requests.HTTPError) as exc_info:
            blogger._fetch_page(session, leaky_url, {}, MagicMock())  # type: ignore[arg-type]
        message = str(exc_info.value)
        assert "SECRETKEY" not in message
        # The non-retryable matcher keys are prefixes of this message, so error classification still works.
        assert "400 Client Error: Bad Request for url: https://www.googleapis.com/blogger/v3" in message


class TestBloggerSourceResponse:
    @parameterized.expand([("posts", "desc"), ("comments", "desc"), ("blogs", "asc"), ("pages", "asc")])
    def test_sort_mode_matches_incremental(self, endpoint: str, expected: str) -> None:
        response = blogger_source(
            api_key="K",
            blog_id="BID",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == expected

    @parameterized.expand([("posts",), ("comments",)])
    def test_incremental_endpoints_partition_by_published(self, endpoint: str) -> None:
        response = blogger_source(
            api_key="K",
            blog_id="BID",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["published"]
        assert response.partition_format == "month"

    @parameterized.expand([("blogs",), ("pages",)])
    def test_full_refresh_endpoints_have_no_partition(self, endpoint: str) -> None:
        response = blogger_source(
            api_key="K",
            blog_id="BID",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.partition_mode is None
        assert response.partition_keys is None
