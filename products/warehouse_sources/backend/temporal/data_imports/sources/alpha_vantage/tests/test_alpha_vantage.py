from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.alpha_vantage import (
    AlphaVantageAPIError,
    AlphaVantageRetryableError,
    _fetch,
    _normalize_key,
    _parse_earnings,
    _parse_overview,
    _parse_quote,
    _parse_reports,
    _parse_time_series,
    _request_params,
    alpha_vantage_source,
    get_rows,
    parse_symbols,
    validate_credentials,
    validate_symbols,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.settings import (
    ALPHA_VANTAGE_ENDPOINTS,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.alpha_vantage"


def _response(*, body: Any = None, status: int = 200, ok: bool = True) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.ok = ok
    response.reason = "Client Error" if status < 500 else "Server Error"
    # Real requests responses expose the full URL (apikey included) on `response.url`.
    response.url = "https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=IBM&apikey=supersecret"
    response.json.return_value = body if body is not None else {}
    return response


def _session_returning(responses: list[MagicMock]) -> MagicMock:
    session = MagicMock()
    session.get.side_effect = responses
    return session


def _collect_rows(batches: Any) -> list[dict]:
    rows: list[dict] = []
    for batch in batches:
        rows.extend(batch)
    return rows


class TestAlphaVantage:
    @parameterized.expand(
        [
            ("ordinal", "1. open", "open"),
            ("ordinal_spaces", "07. latest trading day", "latest_trading_day"),
            ("percent_words", "10. change percent", "change_percent"),
            ("already_clean", "symbol", "symbol"),
        ]
    )
    def test_normalize_key(self, _name: str, raw: str, expected: str) -> None:
        assert _normalize_key(raw) == expected

    @parameterized.expand(
        [
            ("dedup_upper_strip", " ibm, AAPL ,, msft, IBM ", ["IBM", "AAPL", "MSFT"]),
            ("empty", "", []),
            ("only_commas", " , , ", []),
            ("single", "tsla", ["TSLA"]),
        ]
    )
    def test_parse_symbols(self, _name: str, raw: str, expected: list[str]) -> None:
        assert parse_symbols(raw) == expected

    def test_parse_time_series_strips_prefixes_and_injects_symbol(self) -> None:
        body = {
            "Meta Data": {"whatever": 1},
            "Time Series (Daily)": {
                "2024-01-05": {"1. open": "1", "2. high": "2", "3. low": "0.5", "4. close": "1.5", "5. volume": "100"}
            },
        }
        rows = list(_parse_time_series(body, "IBM"))
        assert rows == [
            {
                "symbol": "IBM",
                "date": "2024-01-05",
                "open": "1",
                "high": "2",
                "low": "0.5",
                "close": "1.5",
                "volume": "100",
            }
        ]

    def test_parse_time_series_handles_varying_block_label(self) -> None:
        # Weekly/monthly functions label the block differently, so the parser must not hardcode "Daily".
        body = {"Meta Data": {}, "Weekly Time Series": {"2024-01-05": {"1. open": "1", "4. close": "2"}}}
        rows = list(_parse_time_series(body, "AAPL"))
        assert rows == [{"symbol": "AAPL", "date": "2024-01-05", "open": "1", "close": "2"}]

    def test_parse_time_series_empty(self) -> None:
        assert list(_parse_time_series({"Meta Data": {}}, "IBM")) == []

    def test_parse_quote_injects_symbol_and_snake_cases(self) -> None:
        body = {
            "Global Quote": {
                "01. symbol": "IBM",
                "05. price": "286.25",
                "07. latest trading day": "2026-07-01",
                "10. change percent": "1.79%",
            }
        }
        assert list(_parse_quote(body, "IBM")) == [
            {"symbol": "IBM", "price": "286.25", "latest_trading_day": "2026-07-01", "change_percent": "1.79%"}
        ]

    def test_parse_quote_empty(self) -> None:
        assert list(_parse_quote({"Global Quote": {}}, "IBM")) == []

    def test_parse_overview_normalizes_keys_and_dedupes_symbol(self) -> None:
        # PascalCase response keys must be normalized like every other parser, and the response's own
        # "Symbol" must collapse into the single injected "symbol" column rather than a Symbol/symbol pair.
        rows = list(_parse_overview({"Symbol": "IBM", "Name": "IBM Corp", "PERatio": "20.5"}, "IBM"))
        assert rows == [{"symbol": "IBM", "name": "IBM Corp", "peratio": "20.5"}]

    def test_parse_overview_empty(self) -> None:
        assert list(_parse_overview({}, "IBM")) == []

    def test_parse_reports_flattens_annual_and_quarterly(self) -> None:
        body = {
            "symbol": "IBM",
            "annualReports": [{"fiscalDateEnding": "2025-12-31", "totalRevenue": "1"}],
            "quarterlyReports": [{"fiscalDateEnding": "2025-09-30"}],
        }
        assert list(_parse_reports(body, "IBM")) == [
            {"symbol": "IBM", "report_type": "annual", "fiscalDateEnding": "2025-12-31", "totalRevenue": "1"},
            {"symbol": "IBM", "report_type": "quarterly", "fiscalDateEnding": "2025-09-30"},
        ]

    def test_parse_earnings_flattens_annual_and_quarterly(self) -> None:
        body = {
            "symbol": "IBM",
            "annualEarnings": [{"fiscalDateEnding": "2025-12-31", "reportedEPS": "11.5"}],
            "quarterlyEarnings": [{"fiscalDateEnding": "2025-09-30", "reportedEPS": "2.6"}],
        }
        assert list(_parse_earnings(body, "IBM")) == [
            {"symbol": "IBM", "report_type": "annual", "fiscalDateEnding": "2025-12-31", "reportedEPS": "11.5"},
            {"symbol": "IBM", "report_type": "quarterly", "fiscalDateEnding": "2025-09-30", "reportedEPS": "2.6"},
        ]

    @parameterized.expand(
        [("reports", _parse_reports, "annualReports"), ("earnings", _parse_earnings, "annualEarnings")]
    )
    def test_parse_raises_when_primary_key_missing(self, _name: str, parser: Any, block_key: str) -> None:
        # fiscalDateEnding is a primary key; a report missing it must raise rather than silently yield an
        # unkeyed row that breaks downstream deduplication.
        body = {block_key: [{"totalRevenue": "1"}]}
        with pytest.raises(KeyError):
            list(parser(body, "IBM"))

    @parameterized.expand(
        [
            ("valid", "IBM, AAPL", ["IBM", "AAPL"], None),
            ("empty", "  ", [], "Enter at least one symbol (e.g. IBM, AAPL)"),
            ("at_limit", ",".join(f"SYM{i}" for i in range(100)), None, None),
            ("over_limit", ",".join(f"SYM{i}" for i in range(101)), None, "Too many symbols"),
        ]
    )
    def test_validate_symbols_bounds_the_list(
        self, _name: str, raw: str, expected_parsed: list[str] | None, expected_error_fragment: str | None
    ) -> None:
        parsed, error = validate_symbols(raw)
        if expected_parsed is not None:
            assert parsed == expected_parsed
        if expected_error_fragment is None:
            assert error is None
        else:
            assert error is not None and expected_error_fragment in error

    def test_request_params_adds_outputsize_full_only_for_time_series(self) -> None:
        ts = _request_params(ALPHA_VANTAGE_ENDPOINTS["time_series_daily"], "IBM", "KEY")
        assert ts == {"function": "TIME_SERIES_DAILY", "symbol": "IBM", "apikey": "KEY", "outputsize": "full"}
        quote = _request_params(ALPHA_VANTAGE_ENDPOINTS["global_quote"], "IBM", "KEY")
        assert "outputsize" not in quote

    def test_fetch_returns_body_on_success(self) -> None:
        session = _session_returning([_response(body={"Global Quote": {"01. symbol": "IBM"}})])
        assert _fetch(session, {"function": "GLOBAL_QUOTE"}, MagicMock()) == {"Global Quote": {"01. symbol": "IBM"}}

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_fetch_http_client_error_does_not_leak_apikey(self, _name: str, status: int) -> None:
        session = _session_returning([_response(status=status, ok=False)])
        with pytest.raises(requests.HTTPError) as exc:
            _fetch(session, {"function": "GLOBAL_QUOTE"}, MagicMock())
        # The apikey must never appear in the error message — it's logged downstream via str(error).
        assert "supersecret" not in str(exc.value)
        assert "apikey" not in str(exc.value)

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_fetch_retryable_status_retries_then_raises(self, _name: str, status: int) -> None:
        session = _session_returning([_response(status=status, ok=False)] * 5)
        with patch("time.sleep"), pytest.raises(AlphaVantageRetryableError):
            _fetch(session, {"function": "GLOBAL_QUOTE"}, MagicMock())
        assert session.get.call_count == 5

    def test_fetch_note_envelope_is_retryable(self) -> None:
        # Alpha Vantage signals the per-minute throttle with an HTTP 200 "Note" body.
        session = _session_returning([_response(body={"Note": "call frequency limit"})] * 5)
        with patch("time.sleep"), pytest.raises(AlphaVantageRetryableError):
            _fetch(session, {"function": "GLOBAL_QUOTE"}, MagicMock())
        assert session.get.call_count == 5

    def test_fetch_information_envelope_is_permanent(self) -> None:
        session = _session_returning([_response(body={"Information": "daily limit reached"})])
        with pytest.raises(AlphaVantageAPIError) as exc:
            _fetch(session, {"function": "GLOBAL_QUOTE"}, MagicMock())
        assert "rate_limit_or_premium" in str(exc.value)

    def test_fetch_non_dict_body_is_permanent(self) -> None:
        session = _session_returning([_response(body=["unexpected"])])
        with pytest.raises(AlphaVantageAPIError) as exc:
            _fetch(session, {"function": "GLOBAL_QUOTE"}, MagicMock())
        assert "unexpected_response" in str(exc.value)

    def test_get_rows_fans_out_over_symbols(self) -> None:
        responses = [
            _response(body={"Global Quote": {"01. symbol": "IBM", "05. price": "1"}}),
            _response(body={"Global Quote": {"01. symbol": "AAPL", "05. price": "2"}}),
        ]
        with patch(f"{MODULE}.make_tracked_session", return_value=_session_returning(responses)):
            rows = _collect_rows(get_rows("KEY", ["IBM", "AAPL"], "global_quote", MagicMock()))
        assert [(r["symbol"], r["price"]) for r in rows] == [("IBM", "1"), ("AAPL", "2")]

    def test_get_rows_skips_symbol_on_error_message(self) -> None:
        # An unknown ticker returns an HTTP 200 "Error Message" scoped to that symbol; the rest sync.
        responses = [
            _response(body={"Error Message": "Invalid API call"}),
            _response(body={"Global Quote": {"01. symbol": "AAPL", "05. price": "2"}}),
        ]
        with patch(f"{MODULE}.make_tracked_session", return_value=_session_returning(responses)):
            rows = _collect_rows(get_rows("KEY", ["BADSYM", "AAPL"], "global_quote", MagicMock()))
        assert [r["symbol"] for r in rows] == ["AAPL"]

    def test_get_rows_propagates_permanent_quota_error(self) -> None:
        responses = [_response(body={"Information": "premium endpoint"})]
        with patch(f"{MODULE}.make_tracked_session", return_value=_session_returning(responses)):
            with pytest.raises(AlphaVantageAPIError):
                _collect_rows(get_rows("KEY", ["IBM"], "global_quote", MagicMock()))

    @parameterized.expand(
        [
            ("time_series_daily", ["symbol", "date"], "date"),
            ("global_quote", ["symbol"], None),
            ("company_overview", ["symbol"], None),
            ("income_statement", ["symbol", "fiscalDateEnding", "report_type"], "fiscalDateEnding"),
            ("earnings", ["symbol", "fiscalDateEnding", "report_type"], "fiscalDateEnding"),
        ]
    )
    def test_alpha_vantage_source_maps_primary_keys_and_partitioning(
        self, endpoint: str, expected_keys: list[str], partition_key: str | None
    ) -> None:
        response = alpha_vantage_source("KEY", ["IBM"], endpoint, MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]

    @parameterized.expand(
        [
            ("empty_key", "", 200, {}, False),
            ("error_message", "KEY", 200, {"Error Message": "invalid apikey"}, False),
            ("information", "KEY", 200, {"Information": "daily limit"}, False),
            ("non_200", "KEY", 500, {}, False),
            ("valid", "KEY", 200, {"Global Quote": {"01. symbol": "IBM"}}, True),
        ]
    )
    def test_validate_credentials(self, _name: str, api_key: str, status: int, body: dict, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = _response(body=body, status=status, ok=status == 200)
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            assert validate_credentials(api_key) is expected

    def test_validate_credentials_empty_key_skips_request(self) -> None:
        with patch(f"{MODULE}.make_tracked_session") as make_session:
            assert validate_credentials("   ") is False
        make_session.assert_not_called()
