from datetime import datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack import marketstack
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.marketstack import (
    MarketstackAPIError,
    MarketstackResumeConfig,
    MarketstackRetryableError,
    _fetch_page,
    _format_date,
    get_rows,
    marketstack_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.settings import MARKETSTACK_ENDPOINTS

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.marketstack"


def _response(
    *, data: Any = None, total: int | None = None, status: int = 200, ok: bool = True, error: dict | None = None
) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.ok = ok
    response.reason = "Client Error" if status < 500 else "Server Error"
    # Real requests responses expose the full URL (access_key included) on `response.url`.
    response.url = "https://api.marketstack.com/v1/eod?access_key=supersecret&symbols=AAPL"
    body: dict[str, Any] = {}
    if error is not None:
        body["error"] = error
    else:
        body["data"] = data if data is not None else []
        body["pagination"] = {"limit": 1000, "offset": 0, "count": len(data or []), "total": total}
    response.json.return_value = body
    return response


def _session_returning(responses: list[MagicMock]) -> MagicMock:
    session = MagicMock()
    session.get.side_effect = responses
    return session


def _resume_manager(saved: MarketstackResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = saved is not None
    manager.load_state.return_value = saved
    return manager


def _collect_rows(tables: Any) -> list[dict]:
    rows: list[dict] = []
    for table in tables:
        rows.extend(table.to_pylist())
    return rows


class TestFormatDate:
    @parameterized.expand(
        [
            ("datetime", datetime(2021, 4, 9, 12, 30), "2021-04-09"),
            ("iso_string", "2021-04-09T00:00:00+0000", "2021-04-09"),
            ("date_string", "2020-08-31", "2020-08-31"),
        ]
    )
    def test_formats_to_yyyy_mm_dd(self, _name: str, value: Any, expected: str) -> None:
        assert _format_date(value) == expected


class TestFetchPage:
    def test_returns_body_on_success(self) -> None:
        session = _session_returning([_response(data=[{"symbol": "AAPL"}], total=1)])
        body = _fetch_page(session, "https://api.marketstack.com/v1/eod", {"access_key": "k"}, MagicMock())
        assert body["data"] == [{"symbol": "AAPL"}]

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_http_client_error_raises_without_leaking_key(self, _name: str, status: int) -> None:
        session = _session_returning([_response(status=status, ok=False)])
        with pytest.raises(requests.HTTPError) as exc:
            _fetch_page(session, "https://api.marketstack.com/v1/eod", {"access_key": "k"}, MagicMock())
        # The access_key must never appear in the error message — it's logged downstream via str(error).
        assert "supersecret" not in str(exc.value)
        assert "access_key" not in str(exc.value)

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_retries_then_raises(self, _name: str, status: int) -> None:
        session = _session_returning([_response(status=status, ok=False)] * 5)
        with patch("time.sleep"), pytest.raises(MarketstackRetryableError):
            _fetch_page(session, "https://api.marketstack.com/v1/eod", {"access_key": "k"}, MagicMock())
        assert session.get.call_count == 5

    def test_body_error_envelope_raises_permanent(self) -> None:
        session = _session_returning([_response(error={"code": "invalid_access_key", "message": "bad"})])
        with pytest.raises(MarketstackAPIError) as exc:
            _fetch_page(session, "https://api.marketstack.com/v1/eod", {"access_key": "k"}, MagicMock())
        # The stable [code] token is what get_non_retryable_errors matches on.
        assert "[invalid_access_key]" in str(exc.value)

    def test_body_error_envelope_rate_limit_is_retryable(self) -> None:
        session = _session_returning([_response(error={"code": "rate_limit_reached", "message": "slow down"})] * 5)
        with patch("time.sleep"), pytest.raises(MarketstackRetryableError):
            _fetch_page(session, "https://api.marketstack.com/v1/eod", {"access_key": "k"}, MagicMock())
        assert session.get.call_count == 5


class TestGetRows:
    def test_paginates_until_total_reached(self) -> None:
        page1 = [{"symbol": "AAPL", "date": f"d{i}"} for i in range(2)]
        page2 = [{"symbol": "AAPL", "date": f"d{i}"} for i in range(2, 4)]
        session = _session_returning([_response(data=page1, total=4), _response(data=page2, total=4)])
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            rows = _collect_rows(get_rows("k", "eod", MagicMock(), _resume_manager(), symbols="AAPL", page_size=2))
        assert len(rows) == 4
        assert session.get.call_count == 2

    def test_stops_on_short_page(self) -> None:
        session = _session_returning([_response(data=[{"code": "USD"}], total=None)])
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            rows = _collect_rows(get_rows("k", "currencies", MagicMock(), _resume_manager(), page_size=1000))
        assert [r["code"] for r in rows] == ["USD"]
        assert session.get.call_count == 1

    def test_stops_on_empty_first_page(self) -> None:
        session = _session_returning([_response(data=[], total=0)])
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            rows = _collect_rows(get_rows("k", "currencies", MagicMock(), _resume_manager(), page_size=1000))
        assert rows == []
        assert session.get.call_count == 1

    def test_resumes_from_saved_offset(self) -> None:
        session = _session_returning([_response(data=[{"code": "USD"}], total=None)])
        manager = _resume_manager(MarketstackResumeConfig(next_offset=2000))
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            _collect_rows(get_rows("k", "currencies", MagicMock(), manager, page_size=1000))
        # The first (and only) request must start from the persisted offset, not 0.
        assert session.get.call_args_list[0].kwargs["params"]["offset"] == 2000

    def test_saves_state_after_yielding_a_batch(self) -> None:
        # Batcher flushes at 2000 rows, so two full 2000-row pages force a mid-stream yield + save.
        page1 = [{"code": f"c{i}"} for i in range(2000)]
        page2 = [{"code": f"c{i}"} for i in range(2000, 4000)]
        session = _session_returning([_response(data=page1, total=4000), _response(data=page2, total=4000)])
        manager = _resume_manager()
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            rows = _collect_rows(get_rows("k", "currencies", MagicMock(), manager, page_size=2000))
        assert len(rows) == 4000
        manager.save_state.assert_called_once_with(MarketstackResumeConfig(next_offset=2000))

    def test_time_series_endpoint_requests_ascending_sort(self) -> None:
        session = _session_returning([_response(data=[{"symbol": "AAPL"}], total=None)])
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            _collect_rows(get_rows("k", "eod", MagicMock(), _resume_manager(), symbols="AAPL", page_size=1000))
        params = session.get.call_args_list[0].kwargs["params"]
        assert params["sort"] == "ASC"
        assert params["symbols"] == "AAPL"

    def test_reference_endpoint_sends_no_symbols_or_sort(self) -> None:
        session = _session_returning([_response(data=[{"code": "USD"}], total=None)])
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            _collect_rows(get_rows("k", "currencies", MagicMock(), _resume_manager(), page_size=1000))
        params = session.get.call_args_list[0].kwargs["params"]
        assert "symbols" not in params
        assert "sort" not in params
        assert "date_from" not in params

    def test_incremental_passes_date_from_watermark(self) -> None:
        session = _session_returning([_response(data=[{"symbol": "AAPL"}], total=None)])
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            _collect_rows(
                get_rows(
                    "k",
                    "eod",
                    MagicMock(),
                    _resume_manager(),
                    symbols="AAPL",
                    should_use_incremental_field=True,
                    db_incremental_field_last_value="2021-04-09T00:00:00+0000",
                    page_size=1000,
                )
            )
        params = session.get.call_args_list[0].kwargs["params"]
        assert params["date_from"] == "2021-04-09"

    def test_no_date_from_on_first_incremental_sync(self) -> None:
        # A first incremental sync has no stored watermark, so no date_from should be sent.
        session = _session_returning([_response(data=[{"symbol": "AAPL"}], total=None)])
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            _collect_rows(
                get_rows(
                    "k",
                    "eod",
                    MagicMock(),
                    _resume_manager(),
                    symbols="AAPL",
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=None,
                    page_size=1000,
                )
            )
        assert "date_from" not in session.get.call_args_list[0].kwargs["params"]

    @parameterized.expand([("eod",), ("intraday",), ("splits",), ("dividends",)])
    def test_time_series_endpoints_require_symbols(self, endpoint: str) -> None:
        # Selecting a time-series table with no symbols is a permanent misconfiguration.
        with pytest.raises(MarketstackAPIError) as exc:
            _collect_rows(get_rows("k", endpoint, MagicMock(), _resume_manager(), symbols=None))
        assert "[missing_symbols]" in str(exc.value)

    def test_blank_symbols_treated_as_missing(self) -> None:
        with pytest.raises(MarketstackAPIError):
            _collect_rows(get_rows("k", "eod", MagicMock(), _resume_manager(), symbols="   "))


class TestMarketstackSource:
    @parameterized.expand(
        [
            ("eod", ["symbol", "exchange", "date"], "date"),
            ("intraday", ["symbol", "exchange", "date"], "date"),
            ("splits", ["symbol", "date"], "date"),
            ("dividends", ["symbol", "date"], "date"),
            ("tickers", ["symbol"], None),
            ("exchanges", ["mic"], None),
            ("currencies", ["code"], None),
            ("timezones", ["timezone"], None),
        ]
    )
    def test_source_response_keys_and_partitioning(
        self, endpoint: str, expected_keys: list[str], expected_partition: str | None
    ) -> None:
        response = marketstack_source("k", endpoint, MagicMock(), _resume_manager(), symbols="AAPL")
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == "asc"
        if expected_partition is None:
            assert response.partition_keys is None
        else:
            assert response.partition_keys == [expected_partition]
            assert response.partition_mode == "datetime"

    def test_every_endpoint_builds_a_source_response(self) -> None:
        for endpoint in MARKETSTACK_ENDPOINTS:
            response = marketstack_source("k", endpoint, MagicMock(), _resume_manager(), symbols="AAPL")
            assert response.name == endpoint
            assert callable(response.items)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, {"data": []}, True),
            ("unauthorized", 401, {"error": {"code": "invalid_access_key"}}, False),
            ("ok_status_but_error_body", 200, {"error": {"code": "usage_limit_reached"}}, False),
        ]
    )
    def test_validate_credentials_status_mapping(self, _name: str, status: int, body: dict, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status
        response.json.return_value = body
        session = MagicMock()
        session.get.return_value = response
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            assert validate_credentials("k") is expected

    def test_validate_credentials_handles_network_error(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            assert validate_credentials("k") is False


def test_module_exposes_base_url() -> None:
    assert marketstack.MARKETSTACK_BASE_URL == "https://api.marketstack.com/v1"
