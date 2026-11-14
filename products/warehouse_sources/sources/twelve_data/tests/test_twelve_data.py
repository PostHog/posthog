import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.sources.twelve_data import twelve_data
from products.warehouse_sources.sources.twelve_data._config import TwelveDataSourceConfig
from products.warehouse_sources.sources.twelve_data.settings import ENDPOINTS
from products.warehouse_sources.sources.twelve_data.source import TwelveDataSource
from products.warehouse_sources.sources.twelve_data.twelve_data import (
    TwelveDataError,
    TwelveDataResumeConfig,
    _format_time_bound,
    parse_symbols,
    validate_credentials,
)


def _json(body: Any, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


def _error_body(code: int, message: str) -> dict[str, Any]:
    return {"code": code, "message": message, "status": "error"}


def _time_series_body(symbol: str, datetimes: list[str]) -> dict[str, Any]:
    return {
        "meta": {"symbol": symbol, "interval": "1day"},
        "values": [
            {"datetime": dt, "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "100"}
            for dt in datetimes
        ],
        "status": "ok",
    }


def _run(
    endpoint: str,
    script: Script,
    symbols: str = "AAPL",
    config_start_date: str | None = None,
    resume_state: TwelveDataResumeConfig | None = None,
    **kwargs: Any,
) -> DriveResult:
    config = TwelveDataSourceConfig(api_key="key", symbols=symbols, interval="1day", start_date=config_start_date)
    return SourceDriver(TwelveDataSource(), config).run(endpoint, script, resume_state=resume_state, **kwargs)


class TestParseSymbols:
    @parameterized.expand(
        [
            ("simple", "AAPL,MSFT", ["AAPL", "MSFT"]),
            ("whitespace", " AAPL , MSFT ", ["AAPL", "MSFT"]),
            ("blank_entries", "AAPL,,MSFT,", ["AAPL", "MSFT"]),
            ("duplicates", "AAPL,MSFT,AAPL", ["AAPL", "MSFT"]),
            ("forex_pair", "EUR/USD", ["EUR/USD"]),
            ("empty", "  ", []),
        ]
    )
    def test_parse_symbols(self, _name: str, raw: str, expected: list[str]) -> None:
        assert parse_symbols(raw) == expected


class TestFormatTimeBound:
    @parameterized.expand(
        [
            ("datetime", datetime(2026, 7, 1, 15, 30, 0, tzinfo=UTC), "2026-07-01 15:30:00"),
            ("date", date(2026, 7, 1), "2026-07-01"),
            ("string", "2026-07-01", "2026-07-01"),
        ]
    )
    def test_formats_watermark_for_start_date_param(self, _name: str, value: Any, expected: str) -> None:
        assert _format_time_bound(value) == expected


class TestErrorEnvelope:
    @parameterized.expand(
        [
            ("unauthorized", 401, "**apikey** parameter is incorrect"),
            ("forbidden", 403, "available starting with the Grow plan"),
            ("rate_limited", 429, "You have run out of API credits"),
        ]
    )
    def test_error_envelope_raises_with_code(self, _name: str, code: int, message: str) -> None:
        # The API wraps errors in a JSON envelope (sometimes on HTTP 200) — the raised message must
        # carry the vendor code so get_non_retryable_errors / get_retryable_errors can match it.
        result = _run("quotes", [_json(_error_body(code, message))])

        assert isinstance(result.raised, TwelveDataError)
        assert f"Twelve Data API error {code}" in str(result.raised)

    def test_no_data_in_window_is_empty_not_error(self) -> None:
        # An incremental sync with no new bars gets a code-400 "error" — it must complete cleanly,
        # not fail the job.
        result = _run(
            "time_series",
            [_json(_error_body(400, "No data is available on the specified dates."), status=400)],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-21",
        )

        assert result.raised is None
        assert result.items == []


class TestCatalogEndpoints:
    def test_catalog_does_not_touch_resume_state(self) -> None:
        result = _run("exchanges", [_json({"data": [{"code": "XNGS"}], "status": "ok"})])

        assert result.rows == [{"code": "XNGS"}]
        assert result.saved_states == []


class TestPerSymbolEndpoints:
    def test_quote_single_object_row_drops_status(self) -> None:
        body = {"symbol": "AAPL", "close": "326.47", "status": "ok"}

        result = _run("quotes", [_json(body)])

        assert result.items == [[{"symbol": "AAPL", "close": "326.47"}]]

    @parameterized.expand(
        [
            (
                "statistics_single_object",
                "statistics",
                {
                    "meta": {"symbol": "AAPL", "currency": "USD", "exchange": "NASDAQ"},
                    "statistics": {"valuations_metrics": {"trailing_pe": 39.5}, "financials": {"gross_margin": 0.5}},
                },
                {},
                [
                    {
                        "symbol": "AAPL",
                        "currency": "USD",
                        "valuations_metrics": {"trailing_pe": 39.5},
                        "financials": {"gross_margin": 0.5},
                    }
                ],
            ),
            (
                "balance_sheet_history",
                "balance_sheets",
                {
                    "meta": {"symbol": "AAPL", "currency": "USD", "period": "Quarterly"},
                    "balance_sheet": [
                        {"fiscal_date": "2026-06-30", "quarter": 3, "assets": {"total_assets": 1}},
                        {"fiscal_date": "2026-03-31", "quarter": 2, "assets": {"total_assets": 2}},
                    ],
                },
                {"period": "quarterly", "outputsize": "1000"},
                [
                    {
                        "symbol": "AAPL",
                        "currency": "USD",
                        "period": "Quarterly",
                        "fiscal_date": "2026-06-30",
                        "quarter": 3,
                        "assets": {"total_assets": 1},
                    },
                    {
                        "symbol": "AAPL",
                        "currency": "USD",
                        "period": "Quarterly",
                        "fiscal_date": "2026-03-31",
                        "quarter": 2,
                        "assets": {"total_assets": 2},
                    },
                ],
            ),
            (
                "cash_flow_history",
                "cash_flows",
                {
                    "meta": {"symbol": "AAPL", "currency": "USD", "period": "Quarterly"},
                    "cash_flow": [{"fiscal_date": "2026-06-30", "quarter": 3, "free_cash_flow": 5}],
                },
                {"period": "quarterly", "outputsize": "1000"},
                [
                    {
                        "symbol": "AAPL",
                        "currency": "USD",
                        "period": "Quarterly",
                        "fiscal_date": "2026-06-30",
                        "quarter": 3,
                        "free_cash_flow": 5,
                    }
                ],
            ),
            (
                "income_statement_history",
                "income_statements",
                {
                    "meta": {"symbol": "AAPL", "currency": "USD", "period": "Quarterly"},
                    "income_statement": [
                        {"fiscal_date": "2026-06-30", "quarter": 3, "sales": 10, "operating_expense": {"other": 1}}
                    ],
                },
                {"period": "quarterly", "outputsize": "1000"},
                [
                    {
                        "symbol": "AAPL",
                        "currency": "USD",
                        "period": "Quarterly",
                        "fiscal_date": "2026-06-30",
                        "quarter": 3,
                        "sales": 10,
                        "operating_expense": {"other": 1},
                    }
                ],
            ),
            (
                "institutional_holders_snapshot",
                "institutional_holders",
                {
                    "meta": {"symbol": "AAPL", "currency": "USD"},
                    "institutional_holders": [
                        {"entity_name": "Example Capital", "date_reported": "2026-06-30", "shares": 5},
                        {"entity_name": "Sample Advisors", "date_reported": "2026-09-30", "shares": 3},
                    ],
                },
                {},
                [
                    {
                        "symbol": "AAPL",
                        "currency": "USD",
                        "entity_name": "Example Capital",
                        "date_reported": "2026-06-30",
                        "shares": 5,
                    },
                    {
                        "symbol": "AAPL",
                        "currency": "USD",
                        "entity_name": "Sample Advisors",
                        "date_reported": "2026-09-30",
                        "shares": 3,
                    },
                ],
            ),
        ]
    )
    def test_fundamentals_rows_carry_meta_and_full_history_params(
        self,
        _name: str,
        endpoint: str,
        body: dict[str, Any],
        expected_params: dict[str, str],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        result = _run(endpoint, [_json(body)])

        assert result.raised is None
        assert result.rows == expected_rows
        for key, value in expected_params.items():
            assert result.params(key) == [value]
        assert result.response is not None and result.response.primary_keys
        assert all(key in row for row in result.rows for key in result.response.primary_keys)

    def test_sync_rejects_too_many_symbols(self) -> None:
        # The cap must hold at sync time too, so a stored config can't bypass validation.
        symbols = ",".join(f"S{i}" for i in range(twelve_data.MAX_SYMBOLS + 1))

        result = _run("quotes", [], symbols=symbols)

        assert isinstance(result.raised, TwelveDataError)
        assert "Twelve Data symbol limit exceeded" in str(result.raised)

    def test_resume_skips_completed_symbols(self) -> None:
        result = _run(
            "splits",
            [_json({"meta": {"symbol": "MSFT"}, "splits": [{"date": "2003-02-18", "ratio": 0.5}]})],
            symbols="AAPL,MSFT",
            resume_state=TwelveDataResumeConfig(completed_symbols=["AAPL"]),
        )

        assert len(result.requests) == 1
        assert result.params("symbol") == ["MSFT"]
        assert result.items[0][0]["symbol"] == "MSFT"


class TestTimeSeries:
    def test_config_start_date_used_when_not_incremental(self) -> None:
        with mock.patch.object(twelve_data, "TIME_SERIES_PAGE_SIZE", 2):
            # Short page → no further requests.
            result = _run(
                "time_series", [_json(_time_series_body("AAPL", ["2020-01-02"]))], config_start_date="2020-01-01"
            )

        assert result.params("start_date")[0] == "2020-01-01"

    def test_page_cap_stops_history_walk(self) -> None:
        # An arbitrarily old start date on a minute interval must not walk history unbounded.
        with (
            mock.patch.object(twelve_data, "TIME_SERIES_PAGE_SIZE", 2),
            mock.patch.object(twelve_data, "MAX_TIME_SERIES_PAGES_PER_SYMBOL", 2),
        ):
            result = _run(
                "time_series",
                [
                    _json(_time_series_body("AAPL", ["2026-07-21", "2026-07-20"])),
                    _json(_time_series_body("AAPL", ["2026-07-20", "2026-07-19"])),
                    # Would be page 3 — must never be requested.
                    _json(_time_series_body("AAPL", ["2026-07-19", "2026-07-18"])),
                ],
                config_start_date="2000-01-01",
            )

        assert len(result.requests) == 2
        assert [row["datetime"] for row in result.rows] == ["2026-07-21", "2026-07-20", "2026-07-19"]


def _market_cap_body(symbol: str, dates: list[str]) -> dict[str, Any]:
    return {
        "meta": {"symbol": symbol, "currency": "USD", "exchange": "NASDAQ"},
        "market_cap": [{"date": day, "value": 100} for day in dates],
    }


def _with_endpoint(endpoint: str, **changes: Any) -> Any:
    return mock.patch.dict(ENDPOINTS, {endpoint: dataclasses.replace(ENDPOINTS[endpoint], **changes)})


class TestMarketCap:
    def test_walks_pages_until_a_short_page(self) -> None:
        with _with_endpoint("market_cap", page_size=2):
            result = _run(
                "market_cap",
                [
                    _json(_market_cap_body("AAPL", ["2026-11-13", "2026-11-12"])),
                    _json(_market_cap_body("AAPL", ["2026-11-11"])),
                    # Would be page 3 — must never be requested.
                    _json(_market_cap_body("AAPL", ["2026-11-10"])),
                ],
            )

        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert result.rows == [
            {"symbol": "AAPL", "currency": "USD", "date": "2026-11-13", "value": 100},
            {"symbol": "AAPL", "currency": "USD", "date": "2026-11-12", "value": 100},
            {"symbol": "AAPL", "currency": "USD", "date": "2026-11-11", "value": 100},
        ]
        assert result.saved_states == [TwelveDataResumeConfig(completed_symbols=["AAPL"])]

    @parameterized.expand(
        [
            # The configured start date belongs to the time series table only.
            ("full_refresh_ignores_config_start_date", False, None, None),
            ("incremental_datetime_watermark", True, datetime(2026, 11, 10, 0, 0, tzinfo=UTC), "2026-11-10"),
            ("incremental_date_watermark", True, date(2026, 11, 10), "2026-11-10"),
        ]
    )
    def test_start_date_comes_from_the_watermark_only(
        self, _name: str, incremental: bool, watermark: Any, expected: str | None
    ) -> None:
        result = _run(
            "market_cap",
            [_json(_market_cap_body("AAPL", ["2026-11-13"]))],
            config_start_date="2000-01-01",
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=watermark,
        )

        assert result.params("start_date") == [expected]


class TestCalendars:
    @pytest.fixture(autouse=True)
    def _frozen_today(self) -> Iterator[None]:
        with time_machine.travel(datetime(2026, 11, 14, 12, 0, tzinfo=UTC), tick=False):
            yield

    @parameterized.expand(
        [
            (
                "earnings_under_data_key",
                "earnings_calendar",
                {
                    "earnings": {
                        "2026-11-17": [{"symbol": "EXA", "mic_code": "XNYS", "eps_estimate": 1.2}],
                        "2026-11-18": [{"symbol": "EXB", "mic_code": "XNAS", "eps_estimate": 0.4}],
                    },
                    "status": "ok",
                },
            ),
            (
                "ipo_at_top_level",
                "ipo_calendar",
                {
                    "2026-11-17": [{"symbol": "EXA", "mic_code": "XNYS", "eps_estimate": 1.2}],
                    "2026-11-18": [{"symbol": "EXB", "mic_code": "XNAS", "eps_estimate": 0.4}],
                },
            ),
        ]
    )
    def test_date_keyed_calendar_rows_carry_their_date(self, _name: str, endpoint: str, body: dict) -> None:
        with _with_endpoint(endpoint, chunk_days=None):
            result = _run(endpoint, [_json(body)])

        assert result.raised is None
        assert result.params("start_date") == ["2026-11-07"]
        assert result.params("end_date") == ["2026-12-14"]
        assert result.rows == [
            {"date": "2026-11-17", "symbol": "EXA", "mic_code": "XNYS", "eps_estimate": 1.2},
            {"date": "2026-11-18", "symbol": "EXB", "mic_code": "XNAS", "eps_estimate": 0.4},
        ]
        assert result.saved_states == []

    def test_window_at_the_record_limit_is_split_in_half(self) -> None:
        def body(*days: str) -> dict[str, Any]:
            return {"earnings": {day: [{"symbol": f"S{day[-2:]}", "mic_code": "XNYS"}] for day in days}}

        with (
            mock.patch.object(twelve_data, "CALENDAR_LOOKBACK_DAYS", 0),
            mock.patch.object(twelve_data, "CALENDAR_LOOKAHEAD_DAYS", 3),
            _with_endpoint("earnings_calendar", record_limit=2, chunk_days=4),
        ):
            result = _run(
                "earnings_calendar",
                [
                    # A truncated response at the cap: discarded, then requested again in halves.
                    _json(body("2026-11-14", "2026-11-15")),
                    _json(body("2026-11-14")),
                    _json(body("2026-11-16")),
                ],
            )

        assert result.raised is None
        assert list(zip(result.params("start_date"), result.params("end_date"))) == [
            ("2026-11-14", "2026-11-17"),
            ("2026-11-14", "2026-11-15"),
            ("2026-11-16", "2026-11-17"),
        ]
        assert [row["date"] for row in result.rows] == ["2026-11-14", "2026-11-16"]

    @parameterized.expand(
        [
            ("short_page_ends_walk", [["A", "B"], ["C"]], ["1", "2"], ["A", "B", "C"]),
            ("empty_page_ends_walk", [["A", "B"], []], ["1", "2"], ["A", "B"]),
            # The API ignoring `page` must not loop until the page cap.
            ("repeated_page_ends_walk", [["A", "B"], ["A", "B"]], ["1", "2"], ["A", "B"]),
        ]
    )
    def test_paged_calendar_walk(
        self, _name: str, pages: list[list[str]], expected_pages: list[str], expected_symbols: list[str]
    ) -> None:
        script = [
            _json([{"symbol": symbol, "mic_code": "XNAS", "ex_date": "2026-11-20", "amount": 0.5} for symbol in page])
            for page in pages
        ]

        with _with_endpoint("dividends_calendar", page_size=2):
            result = _run("dividends_calendar", script)

        assert result.raised is None
        assert result.params("page") == expected_pages
        assert result.params("outputsize") == ["2"] * len(expected_pages)
        assert result.params("start_date") == ["2026-11-07"] * len(expected_pages)
        assert [row["symbol"] for row in result.rows] == expected_symbols


class TestSourceResponse:
    @parameterized.expand(
        [
            ("stocks", ["symbol", "mic_code"]),
            ("exchanges", ["code"]),
            ("quotes", ["symbol"]),
            ("dividends", ["symbol", "ex_date"]),
            ("splits", ["symbol", "date"]),
            ("earnings", ["symbol", "date"]),
            ("income_statements", ["symbol", "period", "fiscal_date"]),
            ("fund_holders", ["symbol", "entity_name"]),
            ("splits_calendar", ["symbol", "mic_code", "date"]),
        ]
    )
    def test_primary_keys_and_full_refresh_shape(self, endpoint: str, primary_keys: list[str]) -> None:
        response = _run(endpoint, []).response

        assert response is not None
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_mode is None

    def test_market_cap_is_unordered_and_partitioned_by_date(self) -> None:
        response = _run("market_cap", []).response

        assert response is not None
        assert response.sort_mode is None
        assert response.partition_keys == ["date"]


class TestValidateCredentials:
    def test_valid_key(self) -> None:
        with scripted_network([_json({"current_usage": 0, "plan_limit": 800})]):
            assert validate_credentials("key") == (True, None)

    def test_invalid_key_surfaces_vendor_message(self) -> None:
        with scripted_network([_json(_error_body(401, "**apikey** parameter is incorrect"), status=401)]):
            ok, error = validate_credentials("bad")

        assert ok is False
        assert error is not None and "401" in error
