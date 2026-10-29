from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.twelvedata import (
    TwelveDataSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_data import twelve_data
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_data.source import TwelveDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_data.twelve_data import (
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


class TestSourceResponse:
    @parameterized.expand(
        [
            ("stocks", ["symbol", "mic_code"]),
            ("exchanges", ["code"]),
            ("quotes", ["symbol"]),
            ("dividends", ["symbol", "ex_date"]),
            ("splits", ["symbol", "date"]),
            ("earnings", ["symbol", "date"]),
        ]
    )
    def test_primary_keys_and_full_refresh_shape(self, endpoint: str, primary_keys: list[str]) -> None:
        response = _run(endpoint, []).response

        assert response is not None
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_mode is None


class TestValidateCredentials:
    def test_valid_key(self) -> None:
        with scripted_network([_json({"current_usage": 0, "plan_limit": 800})]):
            assert validate_credentials("key") == (True, None)

    def test_invalid_key_surfaces_vendor_message(self) -> None:
        with scripted_network([_json(_error_body(401, "**apikey** parameter is incorrect"), status=401)]):
            ok, error = validate_credentials("bad")

        assert ok is False
        assert error is not None and "401" in error
