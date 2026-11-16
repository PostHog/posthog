from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from products.warehouse_sources.sources.sdk import UnknownResourceError
from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    always,
    scripted_network,
)
from products.warehouse_sources.sources.twitter._config import TwitterSourceConfig
from products.warehouse_sources.sources.twitter.settings import TWITTER_ENDPOINTS
from products.warehouse_sources.sources.twitter.source import TwitterSource
from products.warehouse_sources.sources.twitter.twitter import (
    TwitterResumeConfig,
    TwitterSearchQueryMissingError,
    TwitterUserNotFoundError,
    endpoint_permissions,
    normalize_username,
    resolve_user_id,
    to_rfc3339,
    usage_days,
    usage_rows,
    validate_credentials,
)

_LOOKUP_PATH = "/2/users/by/username/posthog"


def _json_response(body: dict[str, Any], status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


class TestNormalizeUsername:
    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "@",
            "a" * 16,
            "post hog",
            "post-hog",
            # A pasted profile URL would otherwise be interpolated straight into the request path.
            "https://x.com/posthog",
            "posthog/../../2/users/me",
        ],
    )
    def test_rejects_anything_else(self, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_username(raw)


class TestToRfc3339:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2024, 3, 1, 12, 30, 45, tzinfo=UTC), "2024-03-01T12:30:45Z"),
            # A naive watermark is read as UTC rather than the worker's local zone.
            (datetime(2024, 3, 1, 12, 30, 45), "2024-03-01T12:30:45Z"),
            # Microseconds are dropped: X takes second granularity only.
            (datetime(2024, 3, 1, 12, 30, 45, 987654, tzinfo=UTC), "2024-03-01T12:30:45Z"),
            # The endpoint's `initial_value` arrives as a string on the first incremental run.
            ("2010-11-06T00:00:00Z", "2010-11-06T00:00:00Z"),
            ("2024-03-01T12:30:45+00:00", "2024-03-01T12:30:45Z"),
        ],
    )
    def test_formats_a_watermark(self, value: Any, expected: str) -> None:
        assert to_rfc3339(value) == expected


class TestUsageDays:
    @pytest.mark.parametrize(
        ("last_value", "expected"),
        [
            (None, 90),
            (datetime.now(UTC), 2),
            (datetime.now(UTC) - timedelta(days=10), 12),
            ((datetime.now(UTC) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"), 5),
            # X answers at most 90 days back.
            (datetime.now(UTC) - timedelta(days=200), 90),
            # A watermark ahead of the worker's clock still asks for at least one day.
            (datetime.now(UTC) + timedelta(days=5), 1),
        ],
    )
    def test_covers_every_day_since_the_watermark(self, last_value: Any, expected: int) -> None:
        assert usage_days(last_value) == expected


class TestUsageRows:
    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            ({}, []),
            ({"project_id": "p1", "daily_client_app_usage": []}, []),
            (
                {
                    "project_id": "p1",
                    "daily_client_app_usage": [
                        {
                            "client_app_id": "a1",
                            "usage": [
                                {"date": "2026-11-01T00:00:00.000Z", "usage": "12"},
                                {"date": "2026-11-02T00:00:00.000Z", "usage": None},
                            ],
                            "usage_result_count": 2,
                        },
                        {"client_app_id": "a2", "usage_result_count": 0},
                    ],
                },
                [
                    {"project_id": "p1", "client_app_id": "a1", "date": "2026-11-01T00:00:00.000Z", "usage": 12},
                    {"project_id": "p1", "client_app_id": "a1", "date": "2026-11-02T00:00:00.000Z", "usage": None},
                ],
            ),
            # The project id can sit only on the project-level report, and a client app id can be null.
            (
                {
                    "daily_project_usage": {"project_id": "p2"},
                    "daily_client_app_usage": [
                        {"client_app_id": None, "usage": [{"date": "2026-11-01T00:00:00.000Z", "usage": "n/a"}]}
                    ],
                },
                [{"project_id": "p2", "client_app_id": "", "date": "2026-11-01T00:00:00.000Z", "usage": None}],
            ),
        ],
    )
    def test_flattens_one_row_per_app_per_day(self, data: dict[str, Any], expected: list[dict[str, Any]]) -> None:
        assert usage_rows(data) == expected


class TestResolveUserId:
    def test_raises_when_the_handle_has_no_account(self) -> None:
        with scripted_network(
            [_json_response({"errors": [{"title": "Not Found Error", "detail": "Could not find user"}]})]
        ):
            with pytest.raises(TwitterUserNotFoundError):
                resolve_user_id("token", "posthog")


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "body", "expected_ok", "expected_fragment"),
        [
            (200, {"data": {"id": "1"}}, True, None),
            (402, {"title": "CreditsDepleted"}, False, "run out of API credits"),
            (400, {"title": "Invalid Request"}, False, "Check the handle and bearer token"),
            # X answers an unknown handle with 200 and an `errors` array, not a 404.
            (200, {"errors": [{"title": "Not Found Error"}]}, False, "no account with the handle"),
        ],
    )
    def test_maps_each_response_to_a_message(
        self, status_code: int, body: dict[str, Any], expected_ok: bool, expected_fragment: str | None
    ) -> None:
        with scripted_network(always(_json_response(body, status_code=status_code))):
            ok, message = validate_credentials("token", "posthog")

        assert ok is expected_ok
        if expected_fragment is None:
            assert message is None
        else:
            assert message is not None and expected_fragment in message

    def test_rejects_a_malformed_handle_without_calling_the_api(self) -> None:
        with scripted_network([]) as network:
            ok, message = validate_credentials("token", "https://x.com/posthog")

        assert ok is False
        assert message is not None and "handle" in message
        assert network.requests_log == []


class TestEndpointPermissions:
    def test_reports_the_tables_the_app_cannot_read(self) -> None:
        responses = {
            _LOOKUP_PATH: _json_response({"data": {"id": "7"}}),
            "/2/users/by": _json_response({"data": [{"id": "7"}]}),
            "/2/users/7/tweets": _json_response({"data": []}),
            "/2/users/7/followers": _json_response({"title": "Forbidden"}, status_code=403),
        }

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path not in responses:
                raise UnexpectedRequest(f"no answer for {request.url}")
            return responses[request.path]

        with scripted_network(respond):
            result = endpoint_permissions("token", "posthog", ["Profile", "Posts", "Followers"])

        assert result["Profile"] is None
        assert result["Posts"] is None
        assert result["Followers"] is not None and "API access" in result["Followers"]

    def test_reports_nothing_when_the_handle_will_not_resolve(self) -> None:
        with scripted_network(always(_json_response({"errors": [{"title": "Not Found Error"}]}))):
            assert endpoint_permissions("token", "posthog", ["Posts"]) == {}

    def test_reports_the_search_table_without_a_query_and_sends_no_request(self) -> None:
        with scripted_network([]) as network:
            result = endpoint_permissions("token", "posthog", ["SearchedPosts"], search_query="  ")

        assert result["SearchedPosts"] is not None and "search query" in result["SearchedPosts"]
        assert network.requests_log == []

    @pytest.mark.parametrize(
        ("endpoint", "path", "expected_params"),
        [
            ("SearchedPosts", "/2/tweets/search/recent", {"query": "posthog -from:posthog", "max_results": "10"}),
            ("ApiUsage", "/2/usage/tweets", {"days": "1"}),
        ],
    )
    def test_probes_the_tables_that_need_no_user_id(
        self, endpoint: str, path: str, expected_params: dict[str, str]
    ) -> None:
        with scripted_network(always(_json_response({"data": []}))) as network:
            result = endpoint_permissions("token", "posthog", [endpoint], search_query="posthog -from:posthog")

        assert result == {endpoint: None}
        assert [request.path for request in network.requests_log] == [path]
        for name, value in expected_params.items():
            assert network.requests_log[0].param(name) == value

    def test_treats_a_network_failure_as_reachable(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("/username/posthog"):
                return _json_response({"data": {"id": "7"}})
            raise OSError("connection reset")

        with scripted_network(respond):
            assert endpoint_permissions("token", "posthog", ["Posts"]) == {"Posts": None}


class TestTwitterSourceRequests:
    """Request shaping, pagination and resume, driven through ``rest_api_resource``."""

    @staticmethod
    def _serve(responses: list[ScriptedResponse]) -> Callable[[RecordedRequest], ScriptedResponse]:
        queue = list(responses)

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == _LOOKUP_PATH:
                return _json_response({"data": {"id": "7"}})
            if not queue:
                raise UnexpectedRequest(f"no answer left for {request.url}")
            return queue.pop(0)

        return respond

    def _drive(
        self,
        endpoint: str,
        responses: list[ScriptedResponse],
        *,
        resume_state: TwitterResumeConfig | None = None,
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
        search_query: str | None = None,
    ) -> tuple[list[RecordedRequest], DriveResult]:
        driver = SourceDriver(
            TwitterSource(),
            TwitterSourceConfig(bearer_token="token", username="posthog", search_query=search_query),
        )
        result = driver.run(
            endpoint,
            self._serve(responses),
            resume_state=resume_state,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )
        data_requests = [request for request in result.requests if request.path != _LOOKUP_PATH]
        return data_requests, result

    def test_first_incremental_run_falls_back_to_the_api_floor(self) -> None:
        requests, _ = self._drive(
            "Posts",
            [_json_response({"data": [{"id": "1"}], "meta": {}})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert requests[0].param("start_time") == "2010-11-06T00:00:00Z"

    @pytest.mark.parametrize("endpoint", ["LikedPosts", "Followers", "Following", "OwnedLists"])
    def test_endpoints_without_a_time_filter_never_send_one(self, endpoint: str) -> None:
        requests, _ = self._drive(
            endpoint,
            [_json_response({"data": [{"id": "1"}], "meta": {}})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
        )

        assert "start_time" not in requests[0].query

    @pytest.mark.parametrize(
        ("should_use_incremental_field", "watermark_age", "sends_start_time"),
        [
            (False, None, False),
            (True, None, False),
            (True, timedelta(days=400), False),
            (True, timedelta(days=6, hours=12), False),
            (True, timedelta(days=2), True),
        ],
    )
    def test_search_sends_the_query_and_only_a_start_time_x_will_accept(
        self, should_use_incremental_field: bool, watermark_age: timedelta | None, sends_start_time: bool
    ) -> None:
        watermark = None if watermark_age is None else (datetime.now(UTC) - watermark_age).replace(microsecond=0)

        requests, result = self._drive(
            "SearchedPosts",
            [
                _json_response({"data": [{"id": "1"}], "meta": {"next_token": "page2"}}),
                _json_response({"data": [{"id": "2"}], "meta": {}}),
            ],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=watermark,
            search_query=" posthog -from:posthog ",
        )

        assert [request.path for request in result.requests] == ["/2/tweets/search/recent"] * 2
        assert requests[1].param("pagination_token") == "page2"
        for request in requests:
            assert request.param("query") == "posthog -from:posthog"
            assert request.param("sort_order") == "recency"
            expected = to_rfc3339(watermark) if sends_start_time else None
            assert request.param("start_time") == expected

    @pytest.mark.parametrize("search_query", [None, "", "   "])
    def test_search_without_a_query_fails_before_any_request(self, search_query: str | None) -> None:
        requests, result = self._drive("SearchedPosts", [], search_query=search_query)

        assert isinstance(result.raised, TwitterSearchQueryMissingError)
        assert result.requests == []
        assert "Add a search query to the source settings to sync this table." in str(result.raised)

    @pytest.mark.parametrize(
        ("should_use_incremental_field", "last_value", "expected_days"),
        [
            (False, None, "90"),
            (True, None, "90"),
            (True, datetime.now(UTC) - timedelta(days=3), "5"),
        ],
    )
    def test_usage_asks_for_the_days_since_the_watermark(
        self, should_use_incremental_field: bool, last_value: Any, expected_days: str
    ) -> None:
        body = {
            "data": {
                "project_id": "p1",
                "daily_client_app_usage": [
                    {"client_app_id": "a1", "usage": [{"date": "2026-11-01T00:00:00.000Z", "usage": "4"}]}
                ],
            }
        }
        requests, result = self._drive(
            "ApiUsage",
            [_json_response(body)],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )

        assert [request.path for request in result.requests] == ["/2/usage/tweets"]
        assert requests[0].param("days") == expected_days
        assert result.rows == [
            {"project_id": "p1", "client_app_id": "a1", "date": "2026-11-01T00:00:00.000Z", "usage": 4}
        ]

    def test_profile_queries_the_handle_without_resolving_an_id(self) -> None:
        requests, result = self._drive("Profile", [_json_response({"data": [{"id": "7", "username": "posthog"}]})])

        assert requests[0].path == "/2/users/by"
        assert requests[0].param("usernames") == "posthog"
        assert [request.path for request in result.requests] == ["/2/users/by"]
        assert result.items == [[{"id": "7", "username": "posthog"}]]

    def test_follows_the_next_token_and_saves_it_after_each_page(self) -> None:
        requests, result = self._drive(
            "Posts",
            [
                _json_response({"data": [{"id": "1"}], "meta": {"next_token": "page2"}}),
                _json_response({"data": [{"id": "2"}], "meta": {}}),
            ],
        )

        assert requests[0].param("pagination_token") is None
        assert requests[1].param("pagination_token") == "page2"
        assert [row["id"] for row in result.rows] == ["1", "2"]
        assert result.saved_states == [TwitterResumeConfig(pagination_token="page2")]

    def test_resume_seeds_the_saved_pagination_token(self) -> None:
        requests, _ = self._drive(
            "Posts",
            [_json_response({"data": [{"id": "9"}], "meta": {}})],
            resume_state=TwitterResumeConfig(pagination_token="saved"),
        )

        assert requests[0].param("pagination_token") == "saved"

    def test_starts_from_the_first_page_when_there_is_no_saved_state(self) -> None:
        requests, _ = self._drive("Posts", [_json_response({"data": [{"id": "1"}], "meta": {}})])

        assert requests[0].param("pagination_token") is None


class TestTwitterSourceResponse:
    def test_an_unknown_endpoint_raises_the_retryable_error(self) -> None:
        driver = SourceDriver(TwitterSource(), TwitterSourceConfig(bearer_token="token", username="posthog"))

        result = driver.run("NotAnEndpoint", [])

        assert isinstance(result.raised, UnknownResourceError)

    def test_every_endpoint_path_resolves_to_a_single_placeholder(self) -> None:
        # A stray placeholder would reach X verbatim and 404 the whole table.
        for config in TWITTER_ENDPOINTS.values():
            formatted = config.path.format(user_id="7") if config.needs_user_id else config.path
            assert "{" not in formatted
