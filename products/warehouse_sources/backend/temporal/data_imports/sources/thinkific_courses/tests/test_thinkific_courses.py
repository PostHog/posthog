import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific_courses.settings import (
    THINKIFIC_COURSES_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific_courses.thinkific_courses import (
    THINKIFIC_BASE_URL,
    ThinkificCoursesResumeConfig,
    _client_config,
    _format_incremental_date,
    thinkific_courses_source,
    validate_credentials,
)

# Both the pipeline client (via _client_config) and validate_credentials build their tracked session
# through make_tracked_session imported into the thinkific_courses module, so patch it there.
SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.thinkific_courses.thinkific_courses.make_tracked_session"
# Retries sleep between attempts; patch the backoff clock so retry paths don't stall the suite.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(items: Optional[list[dict[str, Any]]], total_pages: int = 1) -> Response:
    resp = Response()
    resp.status_code = 200
    resp.url = f"{THINKIFIC_BASE_URL}/courses"
    resp._content = json.dumps({"items": items or [], "meta": {"pagination": {"total_pages": total_pages}}}).encode()
    return resp


def _error_response(status: int, reason: str) -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp.url = f"{THINKIFIC_BASE_URL}/courses"
    resp._content = json.dumps({"error": "Authentication Error"}).encode()
    return resp


def _make_manager(resume_state: Optional[ThinkificCoursesResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead. The
    prepared mock carries the request's real url so the client's allowed-hosts guard can parse it.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _run(
    endpoint: str,
    manager: mock.MagicMock,
    responses: list[Response],
    **kwargs: Any,
) -> tuple[mock.MagicMock, list[dict[str, Any]], list[Any]]:
    """Drive thinkific_courses_source with a mocked client session; return (session, snapshots, pages)."""
    with mock.patch(SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        snapshots = _wire(session, responses)
        resp = thinkific_courses_source(
            "key", "sub", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs
        )
        pages = list(cast("Iterable[Any]", resp.items()))
    return session, snapshots, pages


def _rows(pages: list[Any]) -> list[dict[str, Any]]:
    return [row for page in pages for row in page]


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
        manager = _make_manager()
        responses = [
            _response([{"id": 1}], total_pages=3),
            _response([{"id": 2}], total_pages=3),
            _response([{"id": 3}], total_pages=3),
        ]
        _session, snapshots, pages = _run("courses", manager, responses)

        assert _rows(pages) == [{"id": 1}, {"id": 2}, {"id": 3}]

        # First request starts at page=1 with the configured limit; later requests advance by page.
        assert snapshots[0]["params"]["page"] == 1
        assert snapshots[0]["params"]["limit"] == 100
        assert snapshots[1]["params"]["page"] == 2
        assert snapshots[2]["params"]["page"] == 3

        # State saved after each non-terminal page (points at the next page); the last page saves nothing.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            ThinkificCoursesResumeConfig(next_page=2),
            ThinkificCoursesResumeConfig(next_page=3),
        ]

    def test_resume_starts_from_saved_page(self) -> None:
        manager = _make_manager(ThinkificCoursesResumeConfig(next_page=5))
        _, snapshots, pages = _run("courses", manager, [_response([{"id": 99}], total_pages=5)])

        assert _rows(pages) == [{"id": 99}]
        assert snapshots[0]["params"]["page"] == 5
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = _make_manager()
        session, _snapshots, pages = _run("courses", manager, [_response([{"id": 1}], total_pages=1)])

        assert _rows(pages) == [{"id": 1}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


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
        manager = _make_manager()
        _, snapshots, _pages = _run(
            endpoint,
            manager,
            [_response([{"id": 1}], total_pages=1)],
            should_use_incremental_field=should_use,
            db_incremental_field_last_value=value,
        )
        assert ("query[updated_on_or_after]" in snapshots[0]["params"]) is expected_present
        if expected_present:
            assert snapshots[0]["params"]["query[updated_on_or_after]"] == "2026-03-04"


class TestFanout:
    def test_child_requests_bound_per_parent_and_rows_carry_parent_id(self) -> None:
        manager = _make_manager()
        responses = [
            _response([{"id": 11}, {"id": 22}], total_pages=1),  # parent: courses
            _response([{"id": 1, "rating": 5}], total_pages=1),  # reviews for course 11
            _response([{"id": 2, "rating": 4}], total_pages=1),  # reviews for course 22
        ]
        session, snapshots, pages = _run("course_reviews", manager, responses)

        # The parent id resolves into the child's query string (query-param resolve rides in the path).
        assert snapshots[1]["url"] == f"{THINKIFIC_BASE_URL}/course_reviews?course_id=11"
        assert snapshots[2]["url"] == f"{THINKIFIC_BASE_URL}/course_reviews?course_id=22"
        # Child pagination starts fresh per parent and must not be mistaken for a single-entity fetch.
        assert snapshots[1]["params"]["page"] == 1
        assert snapshots[2]["params"]["page"] == 1

        # Child rows aggregate across parents and carry the renamed parent id — the composite
        # primary key (course_id, id) depends on it.
        assert _rows(pages) == [
            {"id": 1, "rating": 5, "course_id": 11},
            {"id": 2, "rating": 4, "course_id": 22},
        ]
        assert session.send.call_count == 3

    def test_fanout_resume_skips_completed_parents(self) -> None:
        manager = _make_manager(
            ThinkificCoursesResumeConfig(completed=["/course_reviews?course_id=11"], current=None, child_state=None)
        )
        responses = [
            _response([{"id": 11}, {"id": 22}], total_pages=1),  # parent: courses
            _response([{"id": 2, "rating": 4}], total_pages=1),  # reviews for course 22 only
        ]
        session, snapshots, pages = _run("course_reviews", manager, responses)

        assert _rows(pages) == [{"id": 2, "rating": 4, "course_id": 22}]
        assert snapshots[1]["url"] == f"{THINKIFIC_BASE_URL}/course_reviews?course_id=22"
        assert session.send.call_count == 2

    def test_fanout_checkpoints_completed_parents(self) -> None:
        manager = _make_manager()
        responses = [
            _response([{"id": 11}], total_pages=1),  # parent: promotions
            _response([{"id": 7, "code": "SAVE"}], total_pages=1),  # coupons for promotion 11
        ]
        _session, _snapshots, pages = _run("coupons", manager, responses)

        assert _rows(pages) == [{"id": 7, "code": "SAVE", "promotion_id": 11}]
        # After the parent's children are fully synced, the checkpoint records it as completed so a
        # retry skips it instead of re-fetching every parent's children.
        final_state = manager.save_state.call_args_list[-1].args[0]
        assert final_state.completed == ["/coupons?promotion_id=11"]
        assert final_state.current is None


class TestErrorHandling:
    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    @mock.patch(SLEEP_PATCH)
    def test_auth_error_raises_matchable_http_error(self, _name: str, status: int, reason: str, _sleep: Any) -> None:
        # A 401/403 must surface as an HTTPError whose message carries the status and host, so
        # get_non_retryable_errors can substring-match it and stop the sync loud.
        manager = _make_manager()
        with pytest.raises(HTTPError) as exc:
            _run("courses", manager, [_error_response(status, reason)])
        message = str(exc.value)
        assert f"{status}" in message
        assert "api.thinkific.com" in message


class TestSourceResponse:
    @parameterized.expand(list(THINKIFIC_COURSES_ENDPOINTS.keys()))
    def test_every_endpoint_builds_a_response_with_its_declared_keys(self, endpoint: str) -> None:
        config = THINKIFIC_COURSES_ENDPOINTS[endpoint]
        manager = _make_manager()
        resp = thinkific_courses_source("k", "s", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)
        assert resp.name == endpoint
        assert resp.primary_keys == config.primary_keys
        assert resp.sort_mode == "asc"
        assert callable(resp.items)

    @parameterized.expand([("enrollments",), ("users",)])
    def test_partitioned_endpoint_partitions_by_created_at(self, endpoint: str) -> None:
        manager = _make_manager()
        resp = thinkific_courses_source("k", "s", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)
        assert resp.partition_mode == "datetime"
        assert resp.partition_keys == ["created_at"]
        assert resp.partition_format == "month"

    def test_fanout_children_use_composite_primary_keys(self) -> None:
        # Child ids aren't documented as globally unique, so the parent id must stay in the key —
        # dropping it seeds duplicate rows and every later merge multi-matches them.
        assert THINKIFIC_COURSES_ENDPOINTS["course_reviews"].primary_keys == ["course_id", "id"]
        assert THINKIFIC_COURSES_ENDPOINTS["coupons"].primary_keys == ["promotion_id", "id"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, 200),
            ("unauthorized", 401, False, 401),
            ("forbidden", 403, False, 403),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool, expected_code: int) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status)
        with mock.patch(SESSION_PATCH, return_value=session):
            is_valid, code = validate_credentials("key", "sub")
        assert is_valid is expected_valid
        assert code == expected_code

    def test_exception_returns_none_status(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("boom")
        with mock.patch(SESSION_PATCH, return_value=session):
            is_valid, code = validate_credentials("key", "sub")
        assert is_valid is False
        assert code is None

    def test_probe_disables_redirects_and_sample_capture_to_protect_customer_data(self) -> None:
        # The X-Auth-API-Key header rides on the probe, so redirects are pinned off to stop a redirect
        # replaying the key off-host. A successful /courses probe also returns real customer data
        # (student names, free-text notes), so capture is off to keep that body out of HTTP sample storage.
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        with mock.patch(SESSION_PATCH, return_value=session) as make_session:
            validate_credentials("key", "sub")
        assert make_session.call_args.kwargs["allow_redirects"] is False
        assert make_session.call_args.kwargs["capture"] is False


class TestPipelineSessionCapture:
    def test_client_config_disables_sample_capture_and_pins_redirects(self) -> None:
        # Thinkific rows carry student names/emails and free-text review and coupon notes the name-based
        # scrubbers can't recognise, so the pipeline session must be built with capture off (bodies stay
        # out of HTTP sample storage), redirects pinned off (the key can't be replayed off-host), and the
        # key registered for log redaction.
        with mock.patch(SESSION_PATCH) as make_session:
            _client_config("key", "sub")
        assert make_session.call_args.kwargs["capture"] is False
        assert make_session.call_args.kwargs["allow_redirects"] is False
        assert make_session.call_args.kwargs["redact_values"] == ("key",)
