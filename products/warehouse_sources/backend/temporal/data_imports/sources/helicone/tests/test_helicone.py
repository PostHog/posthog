from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.helicone import (
    HeliconeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.helicone.helicone import (
    HeliconeResumeConfig,
    _extract_data,
    _format_timestamp,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.helicone.settings import (
    EVAL_SCORES_ENDPOINT,
    PROMPTS_ENDPOINT,
    PROPERTIES_ENDPOINT,
    REQUESTS_ENDPOINT,
    SESSIONS_ENDPOINT,
    USERS_ENDPOINT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.helicone.source import HeliconeSource


def _driver() -> SourceDriver:
    return SourceDriver(HeliconeSource(), HeliconeSourceConfig(api_key="key", region="us"))


class TestExtractData:
    @parameterized.expand(
        [
            ("wrapped", {"data": [{"id": 1}], "error": None}, [{"id": 1}]),
            ("bare_list", [{"id": 2}], [{"id": 2}]),
            ("null_data", {"data": None, "error": None}, []),
            ("missing_data", {}, []),
        ]
    )
    def test_unwraps_result_shapes(self, _name: str, body: Any, expected: list[dict[str, Any]]) -> None:
        assert _extract_data(body, "https://api.helicone.ai/x") == expected

    def test_error_result_raises(self) -> None:
        with pytest.raises(Exception, match="unauthorized"):
            _extract_data({"data": None, "error": "unauthorized"}, "https://api.helicone.ai/x")


class TestFormatTimestamp:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 3, 4, 2, 58, 14, 123000, tzinfo=UTC), "2026-03-04T02:58:14.123Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("string_passthrough", "2026-03-04T00:00:00Z", "2026-03-04T00:00:00Z"),
            ("none", None, None),
        ]
    )
    def test_formats_cursor_values(self, _name: str, value: Any, expected: str | None) -> None:
        assert _format_timestamp(value) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            is_valid, message = validate_credentials("key", "us")

        assert is_valid is expected_valid
        assert network.requests_log[0].path == "/v1/request/query"
        assert network.requests_log[0].json() == {"filter": "all", "limit": 1, "offset": 0}
        if expected_valid:
            assert message is None
        else:
            assert message is not None

    def test_network_error_is_not_valid(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            is_valid, message = validate_credentials("key", "us")

        assert is_valid is False
        assert message is not None
        assert {request.path for request in network.requests_log} == {"/v1/request/query"}

    @parameterized.expand([("us", "https://api.helicone.ai"), ("eu", "https://eu.api.helicone.ai")])
    def test_uses_regional_host(self, region: str, expected_host: str) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("key", region)

        assert network.requests_log[0].url.startswith(expected_host)


class TestRequestsRows:
    def test_full_refresh_pages_until_short_page(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.helicone.helicone.REQUESTS_PAGE_SIZE", 2
        ):
            result = _driver().run(
                REQUESTS_ENDPOINT,
                [
                    ScriptedResponse(json={"data": [{"request_id": "a"}, {"request_id": "b"}], "error": None}),
                    ScriptedResponse(json={"data": [{"request_id": "c"}], "error": None}),
                ],
            )

        assert result.raised is None
        assert [row["request_id"] for row in result.rows] == ["a", "b", "c"]

        bodies = [request.json() for request in result.requests]
        assert [body["offset"] for body in bodies] == [0, 2]
        assert all(body["filter"] == "all" for body in bodies)
        assert all(body["sort"] == {"created_at": "asc"} for body in bodies)

        # State is saved after each yielded page with the cumulative offset.
        assert [state.offset for state in result.saved_states] == [2, 3]

    @time_machine.travel("2026-06-04 12:00:00", tick=False)
    def test_first_incremental_sync_bounds_backfill_to_lookback(self) -> None:
        result = _driver().run(
            REQUESTS_ENDPOINT,
            [ScriptedResponse(json={"data": [], "error": None})],
            should_use_incremental_field=True,
        )

        assert result.raised is None
        body = result.requests[0].json()
        assert body["filter"] == {"request_response_rmt": {"request_created_at": {"gte": "2025-06-04T12:00:00.000Z"}}}

    def test_resume_state_restores_offset_and_pins_cutoff(self) -> None:
        result = _driver().run(
            REQUESTS_ENDPOINT,
            [ScriptedResponse(json={"data": [], "error": None})],
            resume_state=HeliconeResumeConfig(offset=4000, created_after="2026-01-01T00:00:00.000Z"),
            should_use_incremental_field=True,
            # A resumed run must page the window captured at run start, not this newer value.
            db_incremental_field_last_value=datetime(2026, 5, 1, tzinfo=UTC),
        )

        assert result.raised is None
        body = result.requests[0].json()
        assert body["offset"] == 4000
        assert body["filter"] == {"request_response_rmt": {"request_created_at": {"gte": "2026-01-01T00:00:00.000Z"}}}

    def test_api_error_result_raises(self) -> None:
        result = _driver().run(REQUESTS_ENDPOINT, [ScriptedResponse(json={"data": None, "error": "invalid filter"})])

        assert isinstance(result.raised, Exception)
        assert "invalid filter" in str(result.raised)


class TestSessionsRows:
    @time_machine.travel("2026-06-04 12:00:00", tick=False)
    def test_sends_required_params_and_pages_until_short_page(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.helicone.helicone.SESSIONS_PAGE_SIZE", 2
        ):
            result = _driver().run(
                SESSIONS_ENDPOINT,
                [
                    ScriptedResponse(json={"data": [{"session_id": "s1"}, {"session_id": "s2"}], "error": None}),
                    ScriptedResponse(json={"data": [], "error": None}),
                ],
            )

        assert result.raised is None
        assert [row["session_id"] for row in result.rows] == ["s1", "s2"]

        body = result.requests[0].json()
        # These fields are required by the API even when unused; dropping one is a 400.
        assert body["search"] == ""
        assert body["timezoneDifference"] == 0
        assert body["filter"] == "all"
        assert body["timeFilter"] == {"startTimeUnixMs": 0, "endTimeUnixMs": 1780574400000}

    def test_resume_pins_time_window_across_attempts(self) -> None:
        result = _driver().run(
            SESSIONS_ENDPOINT,
            [ScriptedResponse(json={"data": [], "error": None})],
            resume_state=HeliconeResumeConfig(offset=6, end_time_unix_ms=1700000000000),
        )

        assert result.raised is None
        body = result.requests[0].json()
        assert body["offset"] == 6
        # Recomputing "now" on resume would shift rows across page boundaries.
        assert body["timeFilter"]["endTimeUnixMs"] == 1700000000000


class TestUsersRows:
    def test_yields_rows_from_single_unpaginated_request(self) -> None:
        result = _driver().run(
            USERS_ENDPOINT,
            [ScriptedResponse(json={"data": [{"user_id": "u1", "cost": 1.5}], "error": None})],
        )

        assert result.raised is None
        assert result.items == [[{"user_id": "u1", "cost": 1.5}]]
        assert len(result.requests) == 1
        assert result.requests[0].method == "POST"
        assert "timeFilter" in result.requests[0].json()


class TestPromptsRows:
    def test_pages_with_page_numbers_and_handles_bare_array_response(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.helicone.helicone.PROMPTS_PAGE_SIZE", 2
        ):
            result = _driver().run(
                PROMPTS_ENDPOINT,
                [
                    # The prompts endpoint documents a bare-array response (no {data, error} wrapper).
                    ScriptedResponse(json=[{"id": "p1"}, {"id": "p2"}]),
                    ScriptedResponse(json=[{"id": "p3"}]),
                ],
            )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["p1", "p2", "p3"]

        bodies = [request.json() for request in result.requests]
        assert [body["page"] for body in bodies] == [0, 1]
        assert all(body["search"] == "" and body["tagsFilter"] == [] for body in bodies)


class TestPropertiesRows:
    def test_posts_empty_body_and_yields_property_rows(self) -> None:
        result = _driver().run(
            PROPERTIES_ENDPOINT,
            [ScriptedResponse(json={"data": [{"property": "environment"}, {"property": "feature"}], "error": None})],
        )

        assert result.raised is None
        assert result.items == [[{"property": "environment"}, {"property": "feature"}]]
        assert result.requests[0].url == "https://api.helicone.ai/v1/property/query"
        assert result.requests[0].json() == {}


class TestEvalScoresRows:
    def test_gets_and_wraps_score_names_into_rows(self) -> None:
        result = _driver().run(
            EVAL_SCORES_ENDPOINT,
            [ScriptedResponse(json={"data": ["accuracy", "helpfulness"], "error": None})],
        )

        assert result.raised is None
        assert result.items == [[{"score": "accuracy"}, {"score": "helpfulness"}]]
        assert result.requests[0].url == "https://api.helicone.ai/v1/evals/scores"
        assert result.requests[0].method == "GET"


class TestHeliconeSourceResponse:
    @parameterized.expand(
        [
            (SESSIONS_ENDPOINT, ["session_id"]),
            (USERS_ENDPOINT, ["user_id"]),
            (PROMPTS_ENDPOINT, ["id"]),
            (PROPERTIES_ENDPOINT, ["property"]),
            (EVAL_SCORES_ENDPOINT, ["score"]),
        ]
    )
    def test_full_refresh_response_metadata(self, endpoint: str, expected_primary_keys: list[str]) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={"data": []})])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestNonRetryableErrorMessages:
    def test_401_http_error_matches_a_non_retryable_key(self) -> None:
        # `get_non_retryable_errors` matches on substrings of str(exc); this guards the keys
        # against drift from the message `requests.raise_for_status` actually produces.
        from products.warehouse_sources.backend.temporal.data_imports.sources.helicone.source import HeliconeSource

        response = requests.Response()
        response.status_code = 401
        response.url = "https://api.helicone.ai/v1/request/query-clickhouse"
        response.reason = "Unauthorized"

        with pytest.raises(requests.HTTPError) as exc_info:
            response.raise_for_status()

        keys = HeliconeSource().get_non_retryable_errors().keys()
        assert any(key in str(exc_info.value) for key in keys)
