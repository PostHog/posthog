from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.float_app.float_app import (
    DELETE_LOG_LIMIT,
    PER_PAGE,
    REQUEST_TIMEOUT_SECONDS,
    FloatAppResumeConfig,
    ReportWindow,
    _month_windows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.float_app.settings import (
    PUBLIC_HOLIDAY_YEARS_AHEAD,
    PUBLIC_HOLIDAY_YEARS_BACK,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.float_app.source import FloatAppSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.floatapp import (
    FloatAppSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(FloatAppSource(), FloatAppSourceConfig(api_key="tok"))


class TestPagePagination:
    def test_falls_back_to_full_page_heuristic_when_header_absent(self) -> None:
        # No X-Pagination-Pages header: a full page (== PER_PAGE) implies another page may follow; a
        # short page ends the walk. Without this fallback a header-less response truncates at page 1.
        result = _driver().run(
            "roles",
            [
                ScriptedResponse(json=[{"id": str(i)} for i in range(PER_PAGE)]),
                ScriptedResponse(json=[{"id": "last"}]),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == PER_PAGE + 1
        assert result.params("page") == ["1", "2"]

    def test_stops_on_empty_page(self) -> None:
        result = _driver().run("projects", [ScriptedResponse(json=[], headers={"X-Pagination-Pages": "1"})])

        assert result.raised is None
        assert result.rows == []
        assert result.params("page") == ["1"]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "people",
            [ScriptedResponse(json=[{"people_id": "2"}], headers={"X-Pagination-Pages": "2"})],
            resume_state=FloatAppResumeConfig(next_page=2),
        )

        assert result.raised is None
        assert [row["people_id"] for row in result.rows] == ["2"]
        assert result.params("page") == ["2"]


class TestCursorPagination:
    def test_advances_via_cursor_and_stops_on_short_page(self) -> None:
        result = _driver().run(
            "deleted_tasks",
            [
                ScriptedResponse(
                    json=[{"task_id": i} for i in range(DELETE_LOG_LIMIT)],
                    headers={"X-Pagination-Next-Cursor": "c2", "X-Pagination-Has-More": "true"},
                ),
                ScriptedResponse(
                    json=[{"task_id": 999}],
                    headers={"X-Pagination-Next-Cursor": "", "X-Pagination-Has-More": "false"},
                ),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == DELETE_LOG_LIMIT + 1
        assert result.params("limit") == [str(DELETE_LOG_LIMIT), str(DELETE_LOG_LIMIT)]
        assert result.params("cursor") == [None, "c2"]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "deleted_tasks",
            [ScriptedResponse(json=[{"task_id": 999}])],
            resume_state=FloatAppResumeConfig(next_cursor="c2"),
        )

        assert result.raised is None
        assert [row["task_id"] for row in result.rows] == [999]
        assert result.params("cursor") == ["c2"]


class TestValidateCredentials:
    def test_forbidden(self) -> None:
        with scripted_network([ScriptedResponse(status=403)]) as network:
            assert validate_credentials("tok") == (False, 403)

        assert [request.path for request in network.requests_log] == ["/v3/accounts"]


class TestDateWindowEndpoints:
    def test_public_holidays_sends_a_multi_year_window(self) -> None:
        # Without start_date/end_date Float returns the current year only, which would hide the
        # holidays behind historical logged time.
        result = _driver().run(
            "public_holidays",
            [ScriptedResponse(json=[{"id": 1, "region": 2}], headers={"X-Pagination-Pages": "1"})],
        )

        this_year = datetime.now(UTC).year
        assert result.raised is None
        assert result.requests[0].param("start_date") == f"{this_year - PUBLIC_HOLIDAY_YEARS_BACK}-01-01"
        assert result.requests[0].param("end_date") == f"{this_year + PUBLIC_HOLIDAY_YEARS_AHEAD}-12-31"


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

    @mock.patch(MONTH_WINDOWS_PATCH, return_value=WINDOWS)
    def test_resumes_from_the_saved_month(self, _windows: mock.MagicMock) -> None:
        result = _driver().run(
            "reports_people",
            [ScriptedResponse(json={"people": [{"people_id": 2}]})],
            resume_state=FloatAppResumeConfig(next_window_start="2026-02-01"),
        )

        assert result.raised is None
        assert result.params("start_date") == ["2026-02-01"]
        assert [row["people_id"] for row in result.rows] == [2]
        assert [request.read_timeout for request in result.requests] == [REQUEST_TIMEOUT_SECONDS]

    @mock.patch(MONTH_WINDOWS_PATCH, return_value=WINDOWS)
    def test_a_month_with_no_people_yields_nothing_and_still_advances(self, _windows: mock.MagicMock) -> None:
        result = _driver().run(
            "reports_people",
            [
                ScriptedResponse(json={"people": []}),
                ScriptedResponse(json={"people": [{"people_id": 2}]}),
            ],
        )

        assert result.raised is None
        assert [row["people_id"] for row in result.rows] == [2]
        assert result.saved_states == [FloatAppResumeConfig(next_window_start="2026-02-01")]
        assert [request.read_timeout for request in result.requests] == [REQUEST_TIMEOUT_SECONDS] * 2

    @pytest.mark.parametrize("body", [{}, {"people": None}, {"people": {"1": {}}}, []])
    @mock.patch(MONTH_WINDOWS_PATCH, return_value=WINDOWS)
    def test_a_changed_envelope_fails_loud(
        self,
        _windows: mock.MagicMock,
        body: dict[str, Any] | list[Any],
    ) -> None:
        # Silently reading a changed shape as an empty month would drop that month from a table
        # that is fully replaced every sync.
        result = _driver().run("reports_people", [ScriptedResponse(json=body)])

        assert isinstance(result.raised, ValueError)
        assert "people" in str(result.raised)
        assert [request.read_timeout for request in result.requests] == [REQUEST_TIMEOUT_SECONDS]
