import json
from datetime import date
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.float_app.float_app import (
    DELETE_LOG_LIMIT,
    PER_PAGE,
    REQUEST_TIMEOUT_SECONDS,
    FloatAppResumeConfig,
    ReportWindow,
    _month_windows,
    float_app_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.float_app.settings import (
    PUBLIC_HOLIDAY_YEARS_AHEAD,
    PUBLIC_HOLIDAY_YEARS_BACK,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the float_app module.
FLOAT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.float_app.float_app.make_tracked_session"
)


def _response(items: list[dict[str, Any]], headers: dict[str, str] | None = None) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(items).encode()
    if headers:
        resp.headers.update(headers)
    return resp


def _response_body(body: dict[str, Any] | list[Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: FloatAppResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock):
    return float_app_source("tok", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestPagePagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_falls_back_to_full_page_heuristic_when_header_absent(self, MockSession) -> None:
        # No X-Pagination-Pages header: a full page (== PER_PAGE) implies another page may follow; a
        # short page ends the walk. Without this fallback a header-less response truncates at page 1.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": str(i)} for i in range(PER_PAGE)], {}),
                _response([{"id": "last"}], {}),
            ],
        )

        rows = _rows(_source("roles", _make_manager()))

        assert len(rows) == PER_PAGE + 1
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], {"X-Pagination-Pages": "1"})])

        assert _rows(_source("projects", _make_manager())) == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"people_id": "2"}], {"X-Pagination-Pages": "2"})])

        rows = _rows(_source("people", _make_manager(FloatAppResumeConfig(next_page=2))))

        assert [r["people_id"] for r in rows] == ["2"]
        assert params[0]["page"] == 2
        assert session.send.call_count == 1


class TestCursorPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_advances_via_cursor_and_stops_on_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response(
                    [{"task_id": i} for i in range(DELETE_LOG_LIMIT)],
                    {"X-Pagination-Next-Cursor": "c2", "X-Pagination-Has-More": "true"},
                ),
                _response(
                    [{"task_id": 999}],
                    {"X-Pagination-Next-Cursor": "", "X-Pagination-Has-More": "false"},
                ),
            ],
        )

        rows = _rows(_source("deleted_tasks", _make_manager()))

        assert len(rows) == DELETE_LOG_LIMIT + 1
        assert params[0]["limit"] == DELETE_LOG_LIMIT
        assert "cursor" not in params[0]
        assert params[1]["cursor"] == "c2"
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"task_id": 999}], {})])

        rows = _rows(_source("deleted_tasks", _make_manager(FloatAppResumeConfig(next_cursor="c2"))))

        assert [r["task_id"] for r in rows] == [999]
        assert params[0]["cursor"] == "c2"
        assert session.send.call_count == 1


class TestValidateCredentials:
    @mock.patch(FLOAT_SESSION_PATCH)
    def test_forbidden(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=403)
        assert validate_credentials("tok") == (False, 403)


class TestDateWindowEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_public_holidays_sends_a_multi_year_window(self, MockSession) -> None:
        # Without start_date/end_date Float returns the current year only, which would hide the
        # holidays behind historical logged time.
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1, "region": 2}], {"X-Pagination-Pages": "1"})])

        _rows(_source("public_holidays", _make_manager()))

        this_year = date.today().year
        assert params[0]["start_date"] == f"{this_year - PUBLIC_HOLIDAY_YEARS_BACK}-01-01"
        assert params[0]["end_date"] == f"{this_year + PUBLIC_HOLIDAY_YEARS_AHEAD}-12-31"


class TestMonthWindows:
    def test_crosses_the_year_boundary(self) -> None:
        assert _month_windows(date(2026, 1, 5), 2) == [
            ReportWindow(start="2025-12-01", end="2025-12-31"),
            ReportWindow(start="2026-01-01", end="2026-01-31"),
        ]


class TestReportWindows:
    WINDOWS = [
        ReportWindow(start="2026-01-01", end="2026-01-31"),
        ReportWindow(start="2026-02-01", end="2026-02-28"),
    ]
    MONTH_WINDOWS_PATCH = (
        "products.warehouse_sources.backend.temporal.data_imports.sources.float_app.float_app._month_windows"
    )

    def _wire_reports(
        self, MockSession: mock.MagicMock, bodies: list[dict[str, Any] | list[Any]]
    ) -> list[dict[str, Any]]:
        session = MockSession.return_value
        captured: list[dict[str, Any]] = []

        def _get(
            url: str,
            headers: dict[str, str] | None = None,
            params: dict[str, str] | None = None,
            timeout: float | None = None,
        ) -> Response:
            captured.append(dict(params or {}))
            assert timeout == REQUEST_TIMEOUT_SECONDS
            return _response_body(bodies[len(captured) - 1])

        session.get.side_effect = _get
        return captured

    @mock.patch(FLOAT_SESSION_PATCH)
    @mock.patch(MONTH_WINDOWS_PATCH, return_value=WINDOWS)
    def test_resumes_from_the_saved_month(self, _windows, MockSession) -> None:
        params = self._wire_reports(MockSession, [{"people": [{"people_id": 2}]}])

        rows = _rows(_source("reports_people", _make_manager(FloatAppResumeConfig(next_window_start="2026-02-01"))))

        assert [p["start_date"] for p in params] == ["2026-02-01"]
        assert [r["people_id"] for r in rows] == [2]

    @mock.patch(FLOAT_SESSION_PATCH)
    @mock.patch(MONTH_WINDOWS_PATCH, return_value=WINDOWS)
    def test_a_month_with_no_people_yields_nothing_and_still_advances(self, _windows, MockSession) -> None:
        self._wire_reports(MockSession, [{"people": []}, {"people": [{"people_id": 2}]}])

        manager = _make_manager()
        rows = _rows(_source("reports_people", manager))

        assert [r["people_id"] for r in rows] == [2]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [FloatAppResumeConfig(next_window_start="2026-02-01")]

    @pytest.mark.parametrize("body", [{}, {"people": None}, {"people": {"1": {}}}, []])
    @mock.patch(FLOAT_SESSION_PATCH)
    @mock.patch(MONTH_WINDOWS_PATCH, return_value=WINDOWS)
    def test_a_changed_envelope_fails_loud(
        self,
        _windows: mock.MagicMock,
        MockSession: mock.MagicMock,
        body: dict[str, Any] | list[Any],
    ) -> None:
        # Silently reading a changed shape as an empty month would drop that month from a table
        # that is fully replaced every sync.
        self._wire_reports(MockSession, [body, body])

        with pytest.raises(ValueError, match="people"):
            _rows(_source("reports_people", _make_manager()))
