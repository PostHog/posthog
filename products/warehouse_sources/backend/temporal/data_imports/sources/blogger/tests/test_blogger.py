from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.blogger.blogger import (
    BloggerResumeConfig,
    _format_rfc3339,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.blogger.source import BloggerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.blogger import (
    BloggerSourceConfig,
)


def _driver(api_key: str = "K") -> SourceDriver:
    return SourceDriver(BloggerSource(), BloggerSourceConfig(api_key=api_key, blog_id="BID"))


def _page(body: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json=body)


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


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("bad_request", 400, False),
            ("not_found", 404, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_ok: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            ok, error = validate_credentials("K", "BID")

        assert ok is expected_ok
        assert network.requests_log[0].path == "/blogger/v3/blogs/BID"
        if not expected_ok:
            assert error

    def test_probe_sends_key_as_query_auth(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("K", "BID")

        request = network.requests_log[0]
        assert request.path == "/blogger/v3/blogs/BID"
        assert request.param("key") == "K"


class TestGetRows:
    def test_single_object_yields_one_row(self) -> None:
        result = _driver().run("blogs", [_page({"id": "B1", "name": "My blog"})])

        assert result.raised is None
        assert result.rows == [{"id": "B1", "name": "My blog"}]
        assert result.saved_states == []
        assert result.paths == ["/blogger/v3/blogs/BID"]
        # `blogs.get` sends no list params; the key rides via the framework's query-param auth.
        assert result.requests[0].query == {"key": ("K",)}

    def test_api_key_rides_as_query_param_auth(self) -> None:
        result = _driver().run("posts", [_page({"items": [{"id": "p1"}]})])

        assert result.raised is None
        assert result.requests[0].param("key") == "K"

    def test_list_paginates_and_saves_state_only_when_more_pages(self) -> None:
        result = _driver().run(
            "posts",
            [
                _page({"items": [{"id": "p1"}, {"id": "p2"}], "nextPageToken": "T2"}),
                _page({"items": [{"id": "p3"}], "nextPageToken": None}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["p1", "p2", "p3"]
        # State is saved once — after the first page (which had a next token), not after the last.
        assert result.saved_states == [BloggerResumeConfig(page_token="T2")]
        # The second request carries the page token from the first response.
        assert result.params("pageToken") == [None, "T2"]
        # Full refresh sends no startDate.
        assert result.params("startDate") == [None, None]

    def test_posts_sends_max_results_and_order_by(self) -> None:
        result = _driver().run("posts", [_page({"items": [{"id": "p1"}]})])

        assert result.raised is None
        assert result.requests[0].param("maxResults") == "100"
        assert result.requests[0].param("orderBy") == "published"

    def test_incremental_maps_last_value_to_start_date(self) -> None:
        result = _driver().run(
            "posts",
            [_page({"items": [{"id": "p1"}], "nextPageToken": None})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("startDate") == "2026-03-04T02:58:14Z"

    def test_resume_starts_from_saved_page_token(self) -> None:
        result = _driver().run(
            "posts",
            [_page({"items": [{"id": "p9"}], "nextPageToken": None})],
            resume_state=BloggerResumeConfig(page_token="RESUME"),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["p9"]
        assert result.requests[0].param("pageToken") == "RESUME"

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
    def test_empty_items_never_save_state(
        self, _name: str, responses: list[dict[str, Any]], expected_requests: int
    ) -> None:
        result = _driver().run("posts", [_page(body) for body in responses])

        assert result.raised is None
        assert result.rows == []
        # Empty pages never persist a resume token: a crash mid-sequence re-walks the empty pages
        # rather than skipping past them, so no unseen data is missed on resume.
        assert result.saved_states == []
        assert len(result.requests) == expected_requests
        if expected_requests > 1:
            # The continuation token from the empty page still drives the follow-up request.
            assert result.requests[1].param("pageToken") == "T2"


class TestErrorSanitization:
    def test_client_error_strips_api_key_but_keeps_matchable_prefix(self) -> None:
        # The real URL carries the key in the query string; the raised error must not leak it.
        result = _driver("SECRETKEY").run("posts", [ScriptedResponse(status=400, json={})])

        assert isinstance(result.raised, requests.HTTPError)
        message = str(result.raised)
        assert result.requests[0].param("key") == "SECRETKEY"
        assert "SECRETKEY" not in message
        # The non-retryable matcher keys are prefixes of this message, so error classification still works.
        assert "400 Client Error: Bad Request for url: https://www.googleapis.com/blogger/v3" in message


class TestBloggerSourceResponse:
    @parameterized.expand([("posts", "desc"), ("comments", "desc"), ("blogs", "asc"), ("pages", "asc")])
    def test_sort_mode_matches_incremental(self, endpoint: str, expected: str) -> None:
        body: dict[str, Any] = {"id": "B1"} if endpoint == "blogs" else {"items": [{"id": "p1"}]}
        result = _driver().run(endpoint, [_page(body)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        assert result.response.sort_mode == expected

    @parameterized.expand([("posts",), ("comments",)])
    def test_incremental_endpoints_partition_by_published(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_page({"items": [{"id": "p1"}]})])

        assert result.raised is None
        assert result.response is not None
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == ["published"]
        assert result.response.partition_format == "month"

    @parameterized.expand([("blogs",), ("pages",)])
    def test_full_refresh_endpoints_have_no_partition(self, endpoint: str) -> None:
        body: dict[str, Any] = {"id": "B1"} if endpoint == "blogs" else {"items": [{"id": "p1"}]}
        result = _driver().run(endpoint, [_page(body)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.partition_mode is None
        assert result.response.partition_keys is None
