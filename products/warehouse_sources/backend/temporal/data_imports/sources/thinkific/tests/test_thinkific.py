from datetime import UTC, date, datetime
from typing import Any, Optional

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.thinkific import (
    ThinkificSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.settings import THINKIFIC_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.source import ThinkificSource
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.thinkific import (
    ThinkificResumeConfig,
    _format_incremental_date,
    is_valid_subdomain,
    validate_credentials,
)


def _response(items: Optional[list[dict[str, Any]]], total_pages: int = 1) -> ScriptedResponse:
    return ScriptedResponse(json={"meta": {"pagination": {"total_pages": total_pages}}, "items": items or []})


def _error_response(status: int) -> ScriptedResponse:
    return ScriptedResponse(status=status, json={"error": "Authentication Error"})


def _run(
    endpoint: str,
    script: Script,
    resume_state: Optional[ThinkificResumeConfig] = None,
    **inputs: Any,
) -> DriveResult:
    driver = SourceDriver(ThinkificSource(), ThinkificSourceConfig(api_key="key", subdomain="sub"))
    return driver.run(endpoint, script, resume_state=resume_state, **inputs)


class TestFormatIncrementalDate:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 3, 4, 23, 58, tzinfo=UTC), "2026-03-04"),
            ("naive_datetime", datetime(2026, 3, 4, 1, 0), "2026-03-04"),
            ("date", date(2026, 3, 4), "2026-03-04"),
            ("iso_string", "2026-03-04T10:00:00Z", "2026-03-04"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_incremental_date(value) == expected


class TestIsValidSubdomain:
    @parameterized.expand(
        [
            ("simple", "mycompany", True),
            ("hyphenated", "my-company", True),
            ("alnum", "abc123", True),
            ("with_space", "my company", False),
            ("with_dot", "my.company", False),
            ("with_protocol", "https://x", False),
            ("empty", "", False),
        ]
    )
    def test_subdomain(self, _name: str, value: str, expected: bool) -> None:
        assert is_valid_subdomain(value) is expected


class TestPagination:
    def test_fresh_run_paginates_and_saves_after_each_non_terminal_page(self) -> None:
        result = _run(
            "courses",
            [
                _response([{"id": 1}], total_pages=3),
                _response([{"id": 2}], total_pages=3),
                _response([{"id": 3}], total_pages=3),
            ],
        )

        # Each page's rows are yielded as a list[dict]; flattened they preserve order.
        assert result.rows == [{"id": 1}, {"id": 2}, {"id": 3}]

        # First request starts at page=1 with the configured limit; later requests advance by page.
        assert result.params("page") == ["1", "2", "3"]
        assert result.requests[0].param("limit") == "100"

        # State saved after each non-terminal page (points at the next page); the last page saves nothing.
        assert result.saved_states == [ThinkificResumeConfig(next_page=2), ThinkificResumeConfig(next_page=3)]

    def test_resume_starts_from_saved_page(self) -> None:
        result = _run(
            "courses",
            [_response([{"id": 99}], total_pages=5)],
            resume_state=ThinkificResumeConfig(next_page=5),
        )

        assert result.rows == [{"id": 99}]
        assert result.requests[0].param("page") == "5"

    def test_does_not_resume_when_there_is_no_saved_state(self) -> None:
        result = _run("courses", [_response([{"id": 1}], total_pages=1)])

        assert result.requests[0].param("page") == "1"


class TestIncrementalFilter:
    @parameterized.expand(
        [
            # Filter added only when all three hold: endpoint supports it, flag on, cursor present.
            ("flag_off", False, datetime(2026, 3, 4, tzinfo=UTC), False),
            ("cursor_missing", True, None, False),
            ("all_conditions", True, datetime(2026, 3, 4, tzinfo=UTC), True),
        ]
    )
    def test_filter_only_when_all_conditions_hold(
        self, _name: str, should_use: bool, value: Any, expected_present: bool
    ) -> None:
        result = _run(
            "enrollments",
            [_response([{"id": 1}], total_pages=1)],
            should_use_incremental_field=should_use,
            db_incremental_field_last_value=value,
        )
        assert ("query[updated_on_or_after]" in result.requests[0].query) is expected_present


class TestErrorHandling:
    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_auth_error_raises_matchable_http_error(self, _name: str, status: int) -> None:
        # A 401/403 must surface as an HTTPError whose message carries the status and host, so
        # get_non_retryable_errors can substring-match it and stop the sync loud.
        result = _run("courses", [_error_response(status)])

        assert isinstance(result.raised, HTTPError)
        message = str(result.raised)
        assert f"{status}" in message
        assert "api.thinkific.com" in message

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("gateway", 503)])
    def test_retryable_status_is_retried_then_reraised(self, _name: str, status: int) -> None:
        # 429/5xx are retried up to the client cap and then reraised as a retryable error.
        result = _run("courses", always(_error_response(status)))

        assert isinstance(result.raised, RESTClientRetryableError)


class TestSourceResponse:
    @parameterized.expand([("enrollments",), ("users",)])
    def test_partitioned_endpoint_partitions_by_created_at(self, endpoint: str) -> None:
        resp = _run(endpoint, [_response([])]).response

        assert resp is not None
        assert resp.partition_mode == "datetime"
        assert resp.partition_keys == ["created_at"]
        assert resp.partition_format == "month"

    @parameterized.expand(list(THINKIFIC_ENDPOINTS.keys()))
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        resp = _run(endpoint, [_response([])]).response

        assert resp is not None
        assert resp.primary_keys == ["id"]
        assert callable(resp.items)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("forbidden", 403, False, 403),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool, expected_code: int) -> None:
        with scripted_network([ScriptedResponse(status=status, json={})]):
            is_valid, code = validate_credentials("key", "sub")
        assert is_valid is expected_valid
        assert code == expected_code

    def test_probe_disables_redirects_to_protect_api_key(self) -> None:
        # The X-Auth-API-Key header rides on the probe; the session must be built with redirects
        # pinned off so a redirect can't replay the key to the redirect target during validation.
        with scripted_network([ScriptedResponse(json={})]) as network:
            validate_credentials("key", "sub")
        assert network.session_options[0]["allow_redirects"] is False
