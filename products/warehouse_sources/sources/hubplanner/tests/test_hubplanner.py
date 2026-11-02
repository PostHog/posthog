from datetime import UTC, date, datetime

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hubplanner import (
    HubplannerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner.hubplanner import (
    PAGE_SIZE,
    HubPlannerResumeConfig,
    _build_request_plan,
    _format_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner.settings import HUBPLANNER_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner.source import HubplannerSource


def _driver(api_key: str = "k") -> SourceDriver:
    return SourceDriver(HubplannerSource(), HubplannerSourceConfig(api_key=api_key))


class TestFormatValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (
                "datetime_microseconds_truncated_to_millis",
                datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC),
                "2026-01-15T10:30:45.123Z",
            ),
            ("naive_datetime_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
            ("string_passthrough", "5b1977ade02d407011112222", "5b1977ade02d407011112222"),
        ]
    )
    def test_format_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_value(value) == expected


class TestBuildRequestPlan:
    @parameterized.expand(
        [
            ("projects", "/project"),
            ("booking_categories", "/categories"),
            ("cost_categories", "/costCategories"),
            ("project_tags", "/project-tag"),
            ("unassigned_work", "/unassigned-work"),
        ]
    )
    def test_full_refresh_endpoint_uses_unsorted_get(self, endpoint: str, expected_path: str) -> None:
        # No `sort` on full-refresh GET: an unsupported sort field would 400 the whole sync.
        method, path, body, sort_field = _build_request_plan(
            HUBPLANNER_ENDPOINTS[endpoint], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert (method, path, body, sort_field) == ("GET", expected_path, None, None)


class TestPagination:
    def test_paginates_until_short_page_and_saves_state_after_each_full_page(self) -> None:
        full_page = [{"_id": str(i)} for i in range(PAGE_SIZE)]
        short_page = [{"_id": "last"}]
        result = _driver().run("projects", [ScriptedResponse(json=full_page), ScriptedResponse(json=short_page)])

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.params("page") == ["0", "1"]
        assert result.params("limit") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        # State saved once after the first (full) page points at page 1; the short page ends the loop.
        assert result.saved_states == [HubPlannerResumeConfig(page=1)]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "projects", [ScriptedResponse(json=[{"_id": "x"}])], resume_state=HubPlannerResumeConfig(page=3)
        )

        assert result.raised is None
        assert result.params("page") == ["3"]

    def test_incremental_sync_posts_search_body(self) -> None:
        result = _driver().run(
            "bookings",
            [ScriptedResponse(json=[{"_id": "1"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].method == "POST"
        assert result.paths == ["/v1/booking/search"]
        assert result.requests[0].json() == {"updatedDate": {"$gte": "2026-03-04T00:00:00.000Z"}}
        assert result.params("sort") == ["updatedDate"]

    def test_non_list_response_fails_loud(self) -> None:
        # Every list/search endpoint returns a bare JSON array; a stray object means the response
        # shape changed, so fail loud rather than syncing a garbage row.
        result = _driver().run("projects", [ScriptedResponse(json={"message": "unexpected"})])

        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


class TestAuth:
    def test_client_session_built_with_api_key_redacted(self) -> None:
        # The tracked session must be given the key as a redact value — Hub Planner echoes it back
        # in auth-error bodies, so it could otherwise leak into captured samples.
        result = _driver("my-secret-key").run("projects", [ScriptedResponse(json=[{"_id": "1"}])])

        assert result.raised is None
        assert result.session_options[0]["redact_values"] == ("my-secret-key",)
        assert result.requests[0].headers["authorization"] == "my-secret-key"


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_raises_retryable_error(self, _name: str, status_code: int) -> None:
        result = _driver().run("projects", always(ScriptedResponse(status=status_code, json=[])))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5
        assert set(result.paths) == {"/v1/project"}

    def test_auth_error_raises_http_error(self) -> None:
        # A 403 is non-retryable (get_non_retryable_errors maps it) and surfaces as an HTTPError.
        result = _driver().run(
            "projects", [ScriptedResponse(status=403, json={"error": "OAUTH_ERROR_TOKEN_NOT_VALID"})]
        )

        assert isinstance(result.raised, HTTPError)
        assert result.paths == ["/v1/project"]


class TestSourceResponse:
    @parameterized.expand([("vacations",), ("project_tags",), ("unassigned_work",)])
    def test_endpoint_without_partition_key_has_no_partitioning(self, endpoint: str) -> None:
        # These endpoints carry no creation timestamp, so they aren't partitioned.
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.partition_mode is None
        assert result.response.partition_keys is None


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_maps_to_validity(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("some-key") is expected

        assert network.requests_log[0].path == "/v1/project"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["authorization"] == "some-key"

    def test_validate_credentials_redacts_api_key(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("my-secret-key") is True

        assert network.session_options[0]["redact_values"] == ("my-secret-key",)
