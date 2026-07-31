import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.settings import THINKIFIC_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.thinkific import (
    THINKIFIC_BASE_URL,
    ThinkificResumeConfig,
    _format_incremental_date,
    is_valid_subdomain,
    thinkific_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the thinkific module.
THINKIFIC_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.thinkific.make_tracked_session"
)
# Retries sleep between attempts; patch the backoff clock so retry paths don't stall the suite.
SLEEP_PATCH = "tenacity.nap.time.sleep"

_COURSES_URL = f"{THINKIFIC_BASE_URL}/courses"


def _response(items: Optional[list[dict[str, Any]]], total_pages: int = 1, *, drop_items: bool = False) -> Response:
    body: dict[str, Any] = {"meta": {"pagination": {"total_pages": total_pages}}}
    if not drop_items:
        body["items"] = items or []
    resp = Response()
    resp.status_code = 200
    resp.url = _COURSES_URL
    resp._content = json.dumps(body).encode()
    return resp


def _error_response(status: int, reason: str) -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp.url = _COURSES_URL
    resp._content = json.dumps({"error": "Authentication Error"}).encode()
    return resp


def _make_manager(resume_state: Optional[ThinkificResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run shows
    only the final state — snapshot a copy when each request is prepared instead. The prepared mock
    carries a real ``url`` so the client's allowed-hosts guard can parse its host.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = _COURSES_URL
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _run(
    endpoint: str,
    manager: mock.MagicMock,
    responses: list[Response],
    **kwargs: Any,
) -> tuple[mock.MagicMock, list[dict[str, Any]], list[Any]]:
    """Drive thinkific_source with a mocked client session; return (session, param_snapshots, pages)."""
    with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        params = _wire(session, responses)
        resp = thinkific_source(
            "key", "sub", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs
        )
        pages = list(cast("Iterable[Any]", resp.items()))
    return session, params, pages


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
        manager = _make_manager()
        responses = [
            _response([{"id": 1}], total_pages=3),
            _response([{"id": 2}], total_pages=3),
            _response([{"id": 3}], total_pages=3),
        ]
        session, params, pages = _run("courses", manager, responses)

        # Each page's rows are yielded as a list[dict]; flattened they preserve order.
        assert _rows(pages) == [{"id": 1}, {"id": 2}, {"id": 3}]

        # First request starts at page=1 with the configured limit; later requests advance by page.
        assert params[0]["page"] == 1
        assert params[0]["limit"] == 100
        assert params[1]["page"] == 2
        assert params[2]["page"] == 3

        # State saved after each non-terminal page (points at the next page); the last page saves nothing.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [ThinkificResumeConfig(next_page=2), ThinkificResumeConfig(next_page=3)]

    def test_resume_starts_from_saved_page(self) -> None:
        manager = _make_manager(ThinkificResumeConfig(next_page=5))
        _, params, pages = _run("courses", manager, [_response([{"id": 99}], total_pages=5)])

        assert _rows(pages) == [{"id": 99}]
        assert params[0]["page"] == 5
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = _make_manager()
        session, _params, pages = _run("courses", manager, [_response([{"id": 1}], total_pages=1)])

        assert _rows(pages) == [{"id": 1}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    def test_empty_first_page_yields_no_rows_and_makes_one_request(self) -> None:
        manager = _make_manager()
        session, _params, pages = _run("courses", manager, [_response([], total_pages=1)])

        assert _rows(pages) == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = _make_manager()
        _run("courses", manager, [_response([{"id": 1}], total_pages=1)])
        manager.load_state.assert_not_called()


class TestIncrementalFilter:
    def test_incremental_filter_applied_for_enrollments(self) -> None:
        manager = _make_manager()
        _, params, _pages = _run(
            "enrollments",
            manager,
            [_response([{"id": 1}], total_pages=1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params[0]["query[updated_on_or_after]"] == "2026-03-04"

    def test_no_incremental_filter_for_full_refresh_endpoint(self) -> None:
        manager = _make_manager()
        _, params, _pages = _run(
            "courses",
            manager,
            [_response([{"id": 1}], total_pages=1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert "query[updated_on_or_after]" not in params[0]

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
        manager = _make_manager()
        _, params, _pages = _run(
            "enrollments",
            manager,
            [_response([{"id": 1}], total_pages=1)],
            should_use_incremental_field=should_use,
            db_incremental_field_last_value=value,
        )
        assert ("query[updated_on_or_after]" in params[0]) is expected_present


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

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("gateway", 503)])
    @mock.patch(SLEEP_PATCH)
    def test_retryable_status_is_retried_then_reraised(self, _name: str, status: int, _sleep: Any) -> None:
        # 429/5xx are retried up to the client cap and then reraised as a retryable error.
        manager = _make_manager()
        responses = [_error_response(status, "err") for _ in range(5)]
        session = None
        with pytest.raises(RESTClientRetryableError):
            session, _params, _pages = _run("courses", manager, responses)


class TestSourceResponse:
    def test_full_refresh_endpoint_has_no_partitioning(self) -> None:
        manager = _make_manager()
        resp = thinkific_source("k", "s", "courses", team_id=1, job_id="j", resumable_source_manager=manager)
        assert resp.name == "courses"
        assert resp.primary_keys == ["id"]
        assert resp.partition_mode is None
        assert resp.partition_keys is None
        assert resp.sort_mode == "asc"

    @parameterized.expand([("enrollments",), ("users",)])
    def test_partitioned_endpoint_partitions_by_created_at(self, endpoint: str) -> None:
        manager = _make_manager()
        resp = thinkific_source("k", "s", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)
        assert resp.partition_mode == "datetime"
        assert resp.partition_keys == ["created_at"]
        assert resp.partition_format == "month"

    @parameterized.expand(list(THINKIFIC_ENDPOINTS.keys()))
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        manager = _make_manager()
        resp = thinkific_source("k", "s", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)
        assert resp.primary_keys == ["id"]
        assert callable(resp.items)


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
        with mock.patch(THINKIFIC_SESSION_PATCH, return_value=session):
            is_valid, code = validate_credentials("key", "sub")
        assert is_valid is expected_valid
        assert code == expected_code

    def test_exception_returns_none_status(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("boom")
        with mock.patch(THINKIFIC_SESSION_PATCH, return_value=session):
            is_valid, code = validate_credentials("key", "sub")
        assert is_valid is False
        assert code is None

    def test_probe_disables_redirects_to_protect_api_key(self) -> None:
        # The X-Auth-API-Key header rides on the probe; the session must be built with redirects
        # pinned off so a redirect can't replay the key to the redirect target during validation.
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        with mock.patch(THINKIFIC_SESSION_PATCH, return_value=session) as make_session:
            validate_credentials("key", "sub")
        assert make_session.call_args.kwargs["allow_redirects"] is False
