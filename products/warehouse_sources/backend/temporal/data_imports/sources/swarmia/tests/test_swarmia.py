from collections.abc import Callable
from datetime import date

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.swarmia.settings import SWARMIA_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.swarmia.swarmia import (
    SwarmiaResumeConfig,
    SwarmiaRetryableError,
    _build_windows,
    _convert_value,
    _fetch_csv,
    _rename_column,
    _rows_from_csv,
    _window_params,
    check_credentials,
    check_endpoint_access,
    get_rows,
    swarmia_source,
)

_TRACKED_SESSION_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.swarmia.swarmia.make_tracked_session"
)

# The tenacity `@retry` decorator wraps the real function; `__wrapped__` reaches the undecorated
# body so these tests exercise a single call without the retry loop.
_fetch_csv_direct = _fetch_csv.__wrapped__  # type: ignore[attr-defined]

PULL_REQUESTS_CSV = (
    "Start Date,End Date,Parent Team(s),Team,Cycle Time (s),Review Rate (%),Time to first review (s),"
    "PRs merged / week,Merge Time (s),PRs in progress,Contributors\n"
    "2026-06-29,2026-07-05,Platform,Team A,3600,80.5,600,5,7200,3,7\n"
    "2026-06-29,2026-07-05,Platform,Team B,1800,100,300,2,900,1,4\n"
)


def _mock_response(status_code: int = 200, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.text = text
    response.raise_for_status.side_effect = (
        requests.HTTPError(f"{status_code} Client Error", response=response) if status_code >= 400 else None
    )
    return response


def _mock_manager(resume: SwarmiaResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


class TestColumnHandling:
    @parameterized.expand(
        [
            ("documented_rename", "Cycle Time (s)", "cycle_time_seconds"),
            ("plural_parens", "Parent Team(s)", "parent_teams"),
            ("percent_rename", "Change Failure Rate (%)", "change_failure_rate_percent"),
            ("slash_rename", "PRs merged / week", "prs_merged_per_week"),
            ("unknown_header_fallback", "Some New Metric (%)", "some_new_metric_percent"),
            ("unknown_header_slash", "Bugs / sprint", "bugs_per_sprint"),
        ]
    )
    def test_rename_column(self, _name: str, header: str, expected: str) -> None:
        assert _rename_column(header) == expected

    @parameterized.expand(
        [
            ("date_column", "start_date", "2026-06-29", date(2026, 6, 29)),
            ("month_column_yyyy_mm", "month", "2026-06", date(2026, 6, 1)),
            ("unparseable_date_passthrough", "month", "June 2026", "June 2026"),
            ("float_column", "cycle_time_seconds", "3600", 3600.0),
            ("float_column_decimal", "review_rate_percent", "80.5", 80.5),
            ("non_numeric_metric_passthrough", "fte", "n/a", "n/a"),
            ("empty_becomes_none", "team", "", None),
            ("string_column", "team", "Team A", "Team A"),
        ]
    )
    def test_convert_value(self, _name: str, column: str, value: str, expected: object) -> None:
        assert _convert_value(column, value) == expected

    def test_unpivot_capex_employees_rows(self) -> None:
        raw_rows: list[dict[str | None, str]] = [
            {"Employee ID": "E1", "Name": "Alice", "Email": "alice@example.com", "2026-01-01": "0.5", "2026-02-01": ""}
        ]
        rows = _rows_from_csv(SWARMIA_ENDPOINTS["capex_employees"], raw_rows)

        assert rows == [
            {
                "employee_id": "E1",
                "name": "Alice",
                "email": "alice@example.com",
                "month": date(2026, 1, 1),
                "fte": 0.5,
            },
            {
                "employee_id": "E1",
                "name": "Alice",
                "email": "alice@example.com",
                "month": date(2026, 2, 1),
                "fte": None,
            },
        ]


@freeze_time("2026-07-15T12:00:00Z")  # a Wednesday
class TestBuildWindows:
    @parameterized.expand(
        [
            # Mid-week start aligns down to Monday; the current (incomplete) ISO week is excluded.
            (
                "week_alignment_and_completeness",
                "pull_requests",
                date(2026, 6, 30),
                [(date(2026, 6, 29), date(2026, 7, 5)), (date(2026, 7, 6), date(2026, 7, 12))],
            ),
            # The current (incomplete) month is excluded.
            (
                "month_completeness",
                "investment",
                date(2026, 6, 10),
                [(date(2026, 6, 1), date(2026, 6, 30))],
            ),
            ("start_in_future_yields_nothing", "pull_requests", date(2026, 8, 1), []),
            # The current (partial) year is included: capex/employees reports elapsed months.
            (
                "year_windows_include_current_year",
                "capex_employees",
                date(2025, 3, 1),
                [(date(2025, 1, 1), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 12, 31))],
            ),
        ]
    )
    def test_build_windows(
        self, _name: str, endpoint: str, range_start: date, expected: list[tuple[date, date]]
    ) -> None:
        assert _build_windows(SWARMIA_ENDPOINTS[endpoint], range_start, date(2026, 7, 15)) == expected


class TestWindowParams:
    @parameterized.expand(
        [
            (
                "date_range",
                "pull_requests",
                {"startDate": "2026-06-29", "endDate": "2026-07-05"},
            ),
            ("month_param", "fte", {"month": "2026-06"}),
            ("year_param", "capex_employees", {"year": "2026"}),
        ]
    )
    def test_window_params(self, _name: str, endpoint: str, expected: dict[str, str]) -> None:
        assert _window_params(SWARMIA_ENDPOINTS[endpoint], date(2026, 6, 29), date(2026, 7, 5)) == expected


class TestFetchCsv:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(status_code)

        with pytest.raises(SwarmiaRetryableError):
            _fetch_csv_direct(session, "/reports/dora", {}, {}, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_auth_errors_raise_http_error(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(status_code)

        with pytest.raises(requests.HTTPError):
            _fetch_csv_direct(session, "/reports/dora", {}, {}, MagicMock())

    def test_parses_csv_rows(self) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(200, "A,B\n1,2\n")

        rows = _fetch_csv_direct(session, "/reports/dora", {"startDate": "2026-06-29"}, {}, MagicMock())

        assert rows == [{"A": "1", "B": "2"}]
        assert "startDate=2026-06-29" in session.get.call_args[0][0]


@freeze_time("2026-07-15T12:00:00Z")
class TestGetRows:
    @patch(_TRACKED_SESSION_PATH)
    def test_incremental_sync_fetches_complete_windows_after_watermark(self, mock_make_session: MagicMock) -> None:
        session = mock_make_session.return_value
        session.get.return_value = _mock_response(200, PULL_REQUESTS_CSV)
        manager = _mock_manager()

        batches = list(
            get_rows(
                api_key="token",
                endpoint="pull_requests",
                logger=MagicMock(),
                resumable_source_manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 6, 28),
            )
        )

        requested_urls = [call.args[0] for call in session.get.call_args_list]
        assert len(requested_urls) == 2
        assert "startDate=2026-06-29&endDate=2026-07-05" in requested_urls[0]
        assert "startDate=2026-07-06&endDate=2026-07-12" in requested_urls[1]

        assert len(batches) == 2
        first_row = batches[0][0]
        assert first_row["start_date"] == date(2026, 6, 29)
        assert first_row["end_date"] == date(2026, 7, 5)
        assert first_row["team"] == "Team A"
        assert first_row["cycle_time_seconds"] == 3600.0
        assert first_row["review_rate_percent"] == 80.5

    @patch(_TRACKED_SESSION_PATH)
    def test_saves_resume_state_after_each_window_except_last(self, mock_make_session: MagicMock) -> None:
        session = mock_make_session.return_value
        session.get.return_value = _mock_response(200, PULL_REQUESTS_CSV)
        manager = _mock_manager()

        list(
            get_rows(
                api_key="token",
                endpoint="pull_requests",
                logger=MagicMock(),
                resumable_source_manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 6, 28),
            )
        )

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [SwarmiaResumeConfig(next_window_start="2026-07-06")]

    @patch(_TRACKED_SESSION_PATH)
    def test_resumes_from_saved_window_start(self, mock_make_session: MagicMock) -> None:
        session = mock_make_session.return_value
        session.get.return_value = _mock_response(200, PULL_REQUESTS_CSV)
        manager = _mock_manager(resume=SwarmiaResumeConfig(next_window_start="2026-07-06"))

        list(
            get_rows(
                api_key="token",
                endpoint="pull_requests",
                logger=MagicMock(),
                resumable_source_manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 1, 1),
            )
        )

        requested_urls = [call.args[0] for call in session.get.call_args_list]
        assert len(requested_urls) == 1
        assert "startDate=2026-07-06&endDate=2026-07-12" in requested_urls[0]

    @patch(_TRACKED_SESSION_PATH)
    def test_monthly_endpoint_uses_month_param(self, mock_make_session: MagicMock) -> None:
        session = mock_make_session.return_value
        session.get.return_value = _mock_response(
            200, "Month,Author ID,Email,FTE,Swarmia issue type,Issue key\n2026-06,A1,a@example.com,0.25,Epic,ENG-1\n"
        )
        manager = _mock_manager(resume=SwarmiaResumeConfig(next_window_start="2026-06-01"))

        batches = list(
            get_rows(
                api_key="token",
                endpoint="fte",
                logger=MagicMock(),
                resumable_source_manager=manager,
            )
        )

        assert "month=2026-06" in session.get.call_args[0][0]
        assert batches[0][0] == {
            "month": date(2026, 6, 1),
            "author_id": "A1",
            "email": "a@example.com",
            "fte": 0.25,
            "swarmia_issue_type": "Epic",
            "issue_key": "ENG-1",
        }

    @patch(_TRACKED_SESSION_PATH)
    def test_header_only_csv_yields_nothing(self, mock_make_session: MagicMock) -> None:
        session = mock_make_session.return_value
        session.get.return_value = _mock_response(200, "Start Date,End Date,Deployment Count\n")
        manager = _mock_manager()

        batches = list(
            get_rows(
                api_key="token",
                endpoint="dora",
                logger=MagicMock(),
                resumable_source_manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 6, 28),
            )
        )

        assert batches == []


class TestCredentialChecks:
    @parameterized.expand([("valid", 200), ("unauthorized", 401), ("forbidden", 403)])
    @patch(_TRACKED_SESSION_PATH)
    def test_check_credentials_returns_status(self, _name: str, status_code: int, mock_make_session: MagicMock) -> None:
        mock_make_session.return_value.get.return_value = _mock_response(status_code)

        assert check_credentials("token") == status_code

    @patch(_TRACKED_SESSION_PATH)
    def test_check_credentials_network_failure_returns_none(self, mock_make_session: MagicMock) -> None:
        mock_make_session.return_value.get.side_effect = requests.ConnectionError("boom")

        assert check_credentials("token") is None

    @freeze_time("2026-07-15T12:00:00Z")
    @patch(_TRACKED_SESSION_PATH)
    def test_check_endpoint_access_flags_denied_reports(self, mock_make_session: MagicMock) -> None:
        session = mock_make_session.return_value

        def _get(url: str, **kwargs: object) -> MagicMock:
            if "/reports/capex" in url:
                return _mock_response(403)
            return _mock_response(200, "Start Date,End Date\n")

        session.get.side_effect = _get

        results = check_endpoint_access("token", ["pull_requests", "capex"])

        assert results["pull_requests"] is None
        assert results["capex"] is not None and "can't access" in results["capex"]

    @patch(_TRACKED_SESSION_PATH)
    def test_check_endpoint_access_network_blip_is_not_a_permission_error(self, mock_make_session: MagicMock) -> None:
        mock_make_session.return_value.get.side_effect = requests.ConnectionError("boom")

        assert check_endpoint_access("token", ["dora"]) == {"dora": None}


class TestHttpSampleCaptureDisabled:
    # Swarmia CSV exports carry free-text issue titles and custom fields that scrubadub can't
    # reliably redact, so every request path must opt out of HTTP sample capture (capture=False)
    # while still redacting the token. A regression here silently leaks customer data to the
    # shared sample store, so assert the contract at the session boundary for each entry point.
    @parameterized.expand(
        [
            (
                "get_rows",
                lambda: list(
                    get_rows(
                        api_key="token",
                        endpoint="pull_requests",
                        logger=MagicMock(),
                        resumable_source_manager=_mock_manager(),
                    )
                ),
            ),
            ("check_credentials", lambda: check_credentials("token")),
            ("check_endpoint_access", lambda: check_endpoint_access("token", ["pull_requests"])),
        ]
    )
    @freeze_time("2026-07-15T12:00:00Z")
    @patch(_TRACKED_SESSION_PATH)
    def test_every_request_path_disables_capture_and_redacts_token(
        self, _name: str, invoke: Callable[[], object], mock_make_session: MagicMock
    ) -> None:
        mock_make_session.return_value.get.return_value = _mock_response(200, PULL_REQUESTS_CSV)

        invoke()

        assert mock_make_session.call_count >= 1
        for call in mock_make_session.call_args_list:
            assert call.kwargs["capture"] is False
            assert call.kwargs["redact_values"] == ("token",)


class TestSwarmiaSourceResponse:
    @parameterized.expand(
        [
            ("pull_requests", ["start_date", "end_date", "team"], "start_date"),
            ("dora", ["start_date", "end_date"], "start_date"),
            ("investment", ["start_date", "end_date", "investment_category"], "start_date"),
            ("capex", ["month", "employee_id", "capitalizable_work"], None),
            ("capex_employees", ["month", "employee_id"], None),
            ("fte", ["month", "author_id", "issue_key"], None),
        ]
    )
    def test_source_response_shape(self, endpoint: str, primary_keys: list[str], partition_key: str | None) -> None:
        response = swarmia_source(
            api_key="token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_mock_manager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None
