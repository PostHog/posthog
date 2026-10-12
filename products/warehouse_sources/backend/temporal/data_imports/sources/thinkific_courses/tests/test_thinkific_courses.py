from datetime import UTC, date, datetime
from typing import Any, Optional

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.thinkificcourses import (
    ThinkificCoursesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific_courses.settings import (
    THINKIFIC_COURSES_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific_courses.source import (
    ThinkificCoursesSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific_courses.thinkific_courses import (
    ThinkificCoursesResumeConfig,
    _format_incremental_date,
    validate_credentials,
)


def _driver() -> SourceDriver:
    return SourceDriver(ThinkificCoursesSource(), ThinkificCoursesSourceConfig(api_key="key", subdomain="sub"))


def _response(items: Optional[list[dict[str, Any]]], total_pages: int = 1) -> ScriptedResponse:
    return ScriptedResponse(json={"items": items or [], "meta": {"pagination": {"total_pages": total_pages}}})


def _error_response(status: int) -> ScriptedResponse:
    return ScriptedResponse(status=status, json={"error": "Authentication Error"})


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


class TestPagination:
    def test_fresh_run_paginates_and_saves_after_each_non_terminal_page(self) -> None:
        responses = [
            _response([{"id": 1}], total_pages=3),
            _response([{"id": 2}], total_pages=3),
            _response([{"id": 3}], total_pages=3),
        ]
        result = _driver().run("courses", responses)

        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}, {"id": 3}]

        # First request starts at page=1 with the configured limit; later requests advance by page.
        assert result.params("page") == ["1", "2", "3"]
        assert result.params("limit") == ["100", "100", "100"]

        # State saved after each non-terminal page (points at the next page); the last page saves nothing.
        assert result.saved_states == [
            ThinkificCoursesResumeConfig(next_page=2),
            ThinkificCoursesResumeConfig(next_page=3),
        ]

    def test_resume_starts_from_saved_page(self) -> None:
        result = _driver().run(
            "courses", [_response([{"id": 99}], total_pages=5)], resume_state=ThinkificCoursesResumeConfig(next_page=5)
        )

        assert result.raised is None
        assert result.rows == [{"id": 99}]
        assert result.params("page") == ["5"]


class TestIncrementalFilter:
    @parameterized.expand(
        [
            # Filter added only when all three hold: endpoint supports it, flag on, cursor present.
            ("enrollments_all_conditions", "enrollments", True, datetime(2026, 3, 4, tzinfo=UTC), True),
            ("enrollments_flag_off", "enrollments", False, datetime(2026, 3, 4, tzinfo=UTC), False),
            ("enrollments_cursor_missing", "enrollments", True, None, False),
            # Full-refresh endpoints never get the filter, even with flag + cursor set.
            ("courses_never", "courses", True, datetime(2026, 3, 4, tzinfo=UTC), False),
        ]
    )
    def test_filter_only_when_all_conditions_hold(
        self, _name: str, endpoint: str, should_use: bool, value: Any, expected_present: bool
    ) -> None:
        result = _driver().run(
            endpoint,
            [_response([{"id": 1}], total_pages=1)],
            should_use_incremental_field=should_use,
            db_incremental_field_last_value=value,
        )
        assert result.raised is None
        assert (result.requests[0].param("query[updated_on_or_after]") is not None) is expected_present
        if expected_present:
            assert result.requests[0].param("query[updated_on_or_after]") == "2026-03-04"


class TestFanout:
    def test_fanout_resume_skips_completed_parents(self) -> None:
        responses = [
            _response([{"id": 11}, {"id": 22}], total_pages=1),  # parent: courses
            _response([{"id": 2, "rating": 4}], total_pages=1),  # reviews for course 22 only
        ]
        result = _driver().run(
            "course_reviews",
            responses,
            resume_state=ThinkificCoursesResumeConfig(
                completed=["/course_reviews?course_id=11"], current=None, child_state=None
            ),
        )

        assert result.raised is None
        assert result.rows == [{"id": 2, "rating": 4, "course_id": 22}]
        assert result.paths == ["/api/public/v1/courses", "/api/public/v1/course_reviews"]
        assert result.requests[1].param("course_id") == "22"
        assert len(result.requests) == 2


class TestErrorHandling:
    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    def test_auth_error_raises_matchable_http_error(self, _name: str, status: int, reason: str) -> None:
        # A 401/403 must surface as an HTTPError whose message carries the status and host, so
        # get_non_retryable_errors can substring-match it and stop the sync loud.
        result = _driver().run("courses", [_error_response(status)])
        assert isinstance(result.raised, HTTPError)
        message = str(result.raised)
        assert f"{status}" in message
        assert reason in message
        assert "api.thinkific.com" in message


class TestSourceResponse:
    @parameterized.expand(list(THINKIFIC_COURSES_ENDPOINTS.keys()))
    def test_every_endpoint_builds_a_response_with_its_declared_keys(self, endpoint: str) -> None:
        config = THINKIFIC_COURSES_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_response([])])
        assert result.raised is None
        resp = result.response
        assert resp is not None
        assert resp.name == endpoint
        assert resp.primary_keys == config.primary_keys
        assert resp.sort_mode == "asc"
        assert callable(resp.items)

    @parameterized.expand([("enrollments",), ("users",)])
    def test_partitioned_endpoint_partitions_by_created_at(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_response([])])
        assert result.raised is None
        resp = result.response
        assert resp is not None
        assert resp.partition_mode == "datetime"
        assert resp.partition_keys == ["created_at"]
        assert resp.partition_format == "month"

    def test_fanout_children_use_composite_primary_keys(self) -> None:
        # Child ids aren't documented as globally unique, so the parent id must stay in the key —
        # dropping it seeds duplicate rows and every later merge multi-matches them.
        reviews = _driver().run("course_reviews", [_response([])])
        coupons = _driver().run("coupons", [_response([])])
        assert reviews.raised is None
        assert coupons.raised is None
        assert reviews.response is not None
        assert coupons.response is not None
        assert reviews.response.primary_keys == ["course_id", "id"]
        assert coupons.response.primary_keys == ["promotion_id", "id"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, 200),
            ("unauthorized", 401, False, 401),
            ("forbidden", 403, False, 403),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool, expected_code: int) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            is_valid, code = validate_credentials("key", "sub")
        assert is_valid is expected_valid
        assert code == expected_code
        assert network.requests_log[0].path == "/api/public/v1/courses"
        assert network.requests_log[0].headers["x-auth-api-key"] == "key"

    def test_probe_disables_redirects_and_sample_capture_to_protect_customer_data(self) -> None:
        # The X-Auth-API-Key header rides on the probe, so redirects are pinned off to stop a redirect
        # replaying the key off-host. A successful /courses probe also returns real customer data
        # (student names, free-text notes), so capture is off to keep that body out of HTTP sample storage.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("key", "sub")
        assert network.session_options[0]["allow_redirects"] is False
        assert network.session_options[0]["capture"] is False


class TestPipelineSessionCapture:
    def test_client_config_disables_sample_capture_and_pins_redirects(self) -> None:
        # Thinkific rows carry student names/emails and free-text review and coupon notes the name-based
        # scrubbers can't recognise, so the pipeline session must be built with capture off (bodies stay
        # out of HTTP sample storage), redirects pinned off (the key can't be replayed off-host), and the
        # key registered for log redaction.
        result = _driver().run("courses", [_response([])])
        assert result.raised is None
        assert result.session_options[0]["capture"] is False
        assert result.session_options[0]["allow_redirects"] is False
        assert result.session_options[0]["redact_values"] == ("key",)
