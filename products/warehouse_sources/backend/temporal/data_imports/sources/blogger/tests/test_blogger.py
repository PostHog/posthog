import json
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.blogger.blogger import (
    BloggerResumeConfig,
    _format_rfc3339,
    blogger_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth

# blogger builds its (sanitized) tracked session itself, so both the pipeline transport and
# validate_credentials patch the blogger module's make_tracked_session.
BLOGGER_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.blogger.blogger.make_tracked_session"
)


def _response(body: dict[str, Any], *, status_code: int = 200, url: str = "", reason: str = "OK") -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp.reason = reason
    resp.url = url or "https://www.googleapis.com/blogger/v3/x"
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: BloggerResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[requests.Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return snapshots of each request AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"params": dict(request.params or {}), "url": request.url, "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return blogger_source(
        api_key="K",
        blog_id="BID",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


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
    @mock.patch(BLOGGER_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, expected_ok: bool, MockSession: mock.MagicMock) -> None:
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=status)
        ok, error = validate_credentials("K", "BID")
        assert ok is expected_ok
        if not expected_ok:
            assert error

    @mock.patch(BLOGGER_SESSION_PATCH)
    def test_probe_sends_key_as_query_auth(self, MockSession: mock.MagicMock) -> None:
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("K", "BID")
        call = MockSession.return_value.get.call_args
        assert call.args[0].endswith("/blogs/BID")
        auth = call.kwargs["auth"]
        assert isinstance(auth, APIKeyAuth)
        assert (auth.api_key, auth.name, auth.location) == ("K", "key", "query")

    @mock.patch(BLOGGER_SESSION_PATCH)
    def test_network_error_returns_false(self, MockSession: mock.MagicMock) -> None:
        MockSession.return_value.get.side_effect = requests.ConnectionError("boom")
        ok, error = validate_credentials("K", "BID")
        assert ok is False
        assert error


class TestGetRows:
    @mock.patch(BLOGGER_SESSION_PATCH)
    def test_single_object_yields_one_row(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"id": "B1", "name": "My blog"})])

        manager = _make_manager()
        rows = _rows(_source("blogs", manager))

        assert rows == [{"id": "B1", "name": "My blog"}]
        manager.save_state.assert_not_called()
        assert snapshots[0]["url"].endswith("/blogs/BID")
        # `blogs.get` sends no list params; the key rides via the framework's query-param auth.
        assert snapshots[0]["params"] == {}

    @mock.patch(BLOGGER_SESSION_PATCH)
    def test_api_key_rides_as_query_param_auth(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"items": [{"id": "p1"}]})])

        _rows(_source("posts", _make_manager()))

        auth = snapshots[0]["auth"]
        assert isinstance(auth, APIKeyAuth)
        assert (auth.api_key, auth.name, auth.location) == ("K", "key", "query")

    @mock.patch(BLOGGER_SESSION_PATCH)
    def test_list_paginates_and_saves_state_only_when_more_pages(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"items": [{"id": "p1"}, {"id": "p2"}], "nextPageToken": "T2"}),
                _response({"items": [{"id": "p3"}], "nextPageToken": None}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("posts", manager))

        assert [r["id"] for r in rows] == ["p1", "p2", "p3"]
        # State is saved once — after the first page (which had a next token), not after the last.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == BloggerResumeConfig(page_token="T2")
        # The second request carries the page token from the first response.
        assert snapshots[0]["params"].get("pageToken") is None
        assert snapshots[1]["params"]["pageToken"] == "T2"
        # Full refresh sends no startDate.
        assert all("startDate" not in s["params"] for s in snapshots)

    @mock.patch(BLOGGER_SESSION_PATCH)
    def test_posts_sends_max_results_and_order_by(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"items": [{"id": "p1"}]})])

        _rows(_source("posts", _make_manager()))

        assert snapshots[0]["params"]["maxResults"] == 100
        assert snapshots[0]["params"]["orderBy"] == "published"

    @mock.patch(BLOGGER_SESSION_PATCH)
    def test_comments_has_no_order_by(self, MockSession: mock.MagicMock) -> None:
        # comments.listByBlog rejects ordering params, so we never send orderBy for it.
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"items": [{"id": "c1"}]})])

        _rows(_source("comments", _make_manager()))

        assert "orderBy" not in snapshots[0]["params"]

    @mock.patch(BLOGGER_SESSION_PATCH)
    def test_incremental_maps_last_value_to_start_date(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"items": [{"id": "p1"}], "nextPageToken": None})])

        _rows(
            _source(
                "posts",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["startDate"] == "2026-03-04T02:58:14Z"

    @mock.patch(BLOGGER_SESSION_PATCH)
    def test_first_sync_without_last_value_sends_no_start_date(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"items": [{"id": "p1"}], "nextPageToken": None})])

        _rows(
            _source(
                "posts",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
            )
        )

        assert "startDate" not in snapshots[0]["params"]

    @mock.patch(BLOGGER_SESSION_PATCH)
    def test_resume_starts_from_saved_page_token(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"items": [{"id": "p9"}], "nextPageToken": None})])

        manager = _make_manager(BloggerResumeConfig(page_token="RESUME"))
        rows = _rows(_source("posts", manager))

        assert [r["id"] for r in rows] == ["p9"]
        assert snapshots[0]["params"]["pageToken"] == "RESUME"

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
    @mock.patch(BLOGGER_SESSION_PATCH)
    def test_empty_items_never_save_state(
        self, _name: str, responses: list[dict], expected_requests: int, MockSession: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response(body) for body in responses])

        manager = _make_manager()
        rows = _rows(_source("posts", manager))

        assert rows == []
        # Empty pages never persist a resume token: a crash mid-sequence re-walks the empty pages
        # rather than skipping past them, so no unseen data is missed on resume.
        manager.save_state.assert_not_called()
        assert len(snapshots) == expected_requests
        if expected_requests > 1:
            # The continuation token from the empty page still drives the follow-up request.
            assert snapshots[1]["params"]["pageToken"] == "T2"

    @mock.patch(BLOGGER_SESSION_PATCH)
    def test_missing_items_key_is_a_zero_row_page(self, MockSession: mock.MagicMock) -> None:
        # Blogger omits `items` entirely when there is nothing to return — that's a legit empty
        # page, not a changed response shape, so it must not raise.
        session = MockSession.return_value
        _wire(session, [_response({"kind": "blogger#postList"})])

        rows = _rows(_source("posts", _make_manager()))

        assert rows == []


class TestErrorSanitization:
    @mock.patch(BLOGGER_SESSION_PATCH)
    def test_client_error_strips_api_key_but_keeps_matchable_prefix(self, MockSession: mock.MagicMock) -> None:
        # The real URL carries the key in the query string; the raised error must not leak it.
        leaky_url = "https://www.googleapis.com/blogger/v3/blogs/BID/posts?key=SECRETKEY&maxResults=100"
        session = MockSession.return_value
        _wire(session, [_response({}, status_code=400, url=leaky_url, reason="Bad Request")])

        with pytest.raises(requests.HTTPError) as exc_info:
            _rows(_source("posts", _make_manager()))

        message = str(exc_info.value)
        assert "SECRETKEY" not in message
        # The non-retryable matcher keys are prefixes of this message, so error classification still works.
        assert "400 Client Error: Bad Request for url: https://www.googleapis.com/blogger/v3" in message


class TestBloggerSourceResponse:
    @parameterized.expand([("posts", "desc"), ("comments", "desc"), ("blogs", "asc"), ("pages", "asc")])
    @mock.patch(BLOGGER_SESSION_PATCH)
    def test_sort_mode_matches_incremental(self, endpoint: str, expected: str, MockSession: mock.MagicMock) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == expected

    @parameterized.expand([("posts",), ("comments",)])
    @mock.patch(BLOGGER_SESSION_PATCH)
    def test_incremental_endpoints_partition_by_published(self, endpoint: str, MockSession: mock.MagicMock) -> None:
        response = _source(endpoint, _make_manager())
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["published"]
        assert response.partition_format == "month"

    @parameterized.expand([("blogs",), ("pages",)])
    @mock.patch(BLOGGER_SESSION_PATCH)
    def test_full_refresh_endpoints_have_no_partition(self, endpoint: str, MockSession: mock.MagicMock) -> None:
        response = _source(endpoint, _make_manager())
        assert response.partition_mode is None
        assert response.partition_keys is None
