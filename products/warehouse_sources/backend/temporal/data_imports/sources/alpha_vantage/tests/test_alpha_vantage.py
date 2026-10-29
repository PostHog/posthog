from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.alpha_vantage import (
    CSV_CHUNK_SIZE,
    EARNINGS_CALENDAR_HORIZON,
    LISTING_STATES,
    AlphaVantageAPIError,
    AlphaVantageRetryableError,
    _earnings_calendar_rows,
    _fetch,
    _fetch_csv,
    _news_rows,
    _news_time_from,
    _normalize_key,
    _parse_corporate_action,
    _parse_earnings,
    _parse_economic,
    _parse_estimates,
    _parse_etf_profile,
    _parse_insider,
    _parse_institutional,
    _parse_news,
    _parse_overview,
    _parse_quote,
    _parse_reports,
    _parse_time_series,
    _request_params,
    alpha_vantage_source,
    parse_symbols,
    validate_credentials,
    validate_symbols,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.settings import (
    ALPHA_VANTAGE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.source import AlphaVantageSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.alphavantage import (
    AlphaVantageSourceConfig,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.alpha_vantage"


def _driver(symbols: str = "IBM", api_key: str = "KEY") -> SourceDriver:
    return SourceDriver(AlphaVantageSource(), AlphaVantageSourceConfig(api_key=api_key, symbols=symbols))


def _response(*, body: Any = None, status: int = 200, ok: bool = True) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.ok = ok
    response.reason = "Client Error" if status < 500 else "Server Error"
    # Real requests responses expose the full URL (apikey included) on `response.url`.
    response.url = "https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=IBM&apikey=supersecret"
    response.json.return_value = body if body is not None else {}
    return response


def _text_response(text: str, *, status: int = 200, ok: bool = True) -> MagicMock:
    response = _response(status=status, ok=ok)
    response.text = text
    return response


def _session_returning(responses: list[MagicMock]) -> MagicMock:
    session = MagicMock()
    session.get.side_effect = responses
    return session


def _article(url: str, time_published: str) -> dict:
    return {
        "url": url,
        "title": f"headline {url}",
        "time_published": time_published,
        "authors": [],
        "topics": [{"topic": "technology", "relevance_score": "0.9"}],
        "overall_sentiment_score": 0.4,
        "overall_sentiment_label": "Bullish",
        "ticker_sentiment": [{"ticker": "IBM", "ticker_sentiment_label": "Bullish"}],
    }


def _news_response(*articles: dict) -> MagicMock:
    return _response(body={"items": str(len(articles)), "feed": list(articles)})


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

    def test_parse_corporate_action_injects_symbol_and_nulls_placeholders(self) -> None:
        # Old dividends carry the literal string "None" for the dates that were never recorded, which
        # would otherwise land as text in a date column.
        body = {
            "symbol": "IBM",
            "data": [
                {
                    "ex_dividend_date": "2026-08-10",
                    "declaration_date": "2026-07-22",
                    "record_date": "2026-08-10",
                    "payment_date": "2026-09-10",
                    "amount": "1.69",
                },
                {
                    "ex_dividend_date": "1999-02-08",
                    "declaration_date": "None",
                    "record_date": "None",
                    "payment_date": "None",
                    "amount": "0.22",
                },
            ],
        }
        assert list(_parse_corporate_action(body, "IBM")) == [
            {
                "symbol": "IBM",
                "ex_dividend_date": "2026-08-10",
                "declaration_date": "2026-07-22",
                "record_date": "2026-08-10",
                "payment_date": "2026-09-10",
                "amount": "1.69",
            },
            {
                "symbol": "IBM",
                "ex_dividend_date": "1999-02-08",
                "declaration_date": None,
                "record_date": None,
                "payment_date": None,
                "amount": "0.22",
            },
        ]

    @parameterized.expand(
        [
            (
                "splits",
                {"symbol": "IBM", "data": [{"effective_date": "2021-11-04", "split_factor": "1.0460"}]},
                {"symbol": "IBM", "effective_date": "2021-11-04", "split_factor": "1.0460"},
            ),
            (
                "shares_outstanding",
                {
                    "symbol": "IBM",
                    "status": "success",
                    "data": [
                        {
                            "date": "2026-06-30",
                            "shares_outstanding_diluted": "951000000",
                            "shares_outstanding_basic": "None",
                        }
                    ],
                },
                {
                    "symbol": "IBM",
                    "date": "2026-06-30",
                    "shares_outstanding_diluted": "951000000",
                    "shares_outstanding_basic": None,
                },
            ),
        ]
    )
    def test_parse_corporate_action_handles_other_shapes(self, _name: str, body: dict, expected: dict) -> None:
        assert list(_parse_corporate_action(body, "IBM")) == [expected]

    def test_parse_estimates_keeps_both_horizons_for_one_date(self) -> None:
        # A fiscal year and its last quarter share an end date, so both rows must survive with their horizon.
        body = {
            "symbol": "IBM",
            "estimates": [
                {"date": "2026-12-31", "horizon": "fiscal year", "eps_estimate_average": "12.40"},
                {
                    "date": "2026-12-31",
                    "horizon": "fiscal quarter",
                    "eps_estimate_average": "4.10",
                    "eps_estimate_revision_down_trailing_7_days": None,
                },
                "not a dict",
            ],
        }
        assert list(_parse_estimates(body, "IBM")) == [
            {"symbol": "IBM", "date": "2026-12-31", "horizon": "fiscal year", "eps_estimate_average": "12.40"},
            {
                "symbol": "IBM",
                "date": "2026-12-31",
                "horizon": "fiscal quarter",
                "eps_estimate_average": "4.10",
                "eps_estimate_revision_down_trailing_7_days": None,
            },
        ]

    @parameterized.expand(
        [("missing_estimates", {"symbol": "IBM"}), ("not_a_list", {"symbol": "IBM", "estimates": {}})]
    )
    def test_parse_estimates_empty(self, _name: str, body: dict) -> None:
        assert list(_parse_estimates(body, "IBM")) == []

    def test_parse_etf_profile_yields_one_row_with_nested_arrays(self) -> None:
        sectors = [{"sector": "INFORMATION TECHNOLOGY", "weight": "0.5"}]
        holdings = [
            {"symbol": "ABCD", "description": "EXAMPLE CORP", "weight": "0.08"},
            {"symbol": "n/a", "description": "CASH", "weight": "0.01"},
        ]
        body = {
            "net_assets": "1000000",
            "dividend_yield": "None",
            "inception_date": "2001-02-03",
            "sectors": sectors,
            "holdings": holdings,
        }
        assert list(_parse_etf_profile(body, "EXMP")) == [
            {
                "symbol": "EXMP",
                "net_assets": "1000000",
                "dividend_yield": None,
                "inception_date": "2001-02-03",
                "sectors": sectors,
                "holdings": holdings,
            }
        ]

    def test_parse_etf_profile_empty(self) -> None:
        assert list(_parse_etf_profile({}, "IBM")) == []

    @parameterized.expand(
        [
            ("value", "4.25", None, {"value": "4.25"}),
            # FRED's placeholder for a period with no observation, verbatim from the live API.
            ("fred_missing_marker", ".", None, {"value": None}),
            ("null_placeholder", "None", None, {"value": None}),
            ("maturity_tagged", "4.25", "10year", {"value": "4.25", "maturity": "10year"}),
        ]
    )
    def test_parse_economic(self, _name: str, value: str, maturity: str | None, expected: dict) -> None:
        body = {
            "name": "Example Rate",
            "interval": "monthly",
            "unit": "percent",
            "data": [{"date": "2026-09-01", "value": value}],
        }
        assert list(_parse_economic(body, maturity)) == [
            {"name": "Example Rate", "interval": "monthly", "unit": "percent", "date": "2026-09-01", **expected}
        ]

    @parameterized.expand([("missing_data", {"name": "x"}), ("not_a_list", {"data": {}})])
    def test_parse_economic_empty(self, _name: str, body: dict) -> None:
        assert list(_parse_economic(body, None)) == []

    @parameterized.expand(
        [
            ("real_gdp", "REAL_GDP", "quarterly", [None]),
            ("cpi", "CPI", "monthly", [None]),
            ("unemployment", "UNEMPLOYMENT", None, [None]),
            ("federal_funds_rate", "FEDERAL_FUNDS_RATE", "daily", [None]),
            ("treasury_yield", "TREASURY_YIELD", "daily", ["3month", "2year", "5year", "7year", "10year", "30year"]),
        ]
    )
    def test_get_rows_requests_economic_series_once_per_maturity_without_symbols(
        self, endpoint: str, function: str, interval: str | None, maturities: list[str | None]
    ) -> None:
        body = {
            "name": "Series",
            "interval": interval,
            "unit": "percent",
            "data": [{"date": "2026-09-01", "value": "1"}],
        }
        result = _driver("IBM, AAPL").run(endpoint, [ScriptedResponse(json=body) for _ in maturities])
        assert result.raised is None
        assert result.params("function") == [function] * len(maturities)
        assert result.params("interval") == [interval] * len(maturities)
        assert result.params("maturity") == maturities
        assert result.params("symbol") == [None] * len(maturities)
        assert [row.get("maturity") for row in result.rows] == maturities

    def test_get_rows_fails_an_economic_series_on_error_message(self) -> None:
        result = _driver().run("cpi", [ScriptedResponse(json={"Error Message": "Invalid API call"})])
        assert isinstance(result.raised, AlphaVantageAPIError)
        assert result.rows == []

    @parameterized.expand(
        [
            ("shares_outstanding", "SHARES_OUTSTANDING", {"data": [{"date": "2026-06-30"}]}),
            (
                "earnings_estimates",
                "EARNINGS_ESTIMATES",
                {"estimates": [{"date": "2026-12-31", "horizon": "fiscal year"}]},
            ),
            ("etf_profile", "ETF_PROFILE", {"net_assets": "1"}),
        ]
    )
    def test_get_rows_fans_new_symbol_tables_out_over_symbols(self, endpoint: str, function: str, body: dict) -> None:
        result = _driver("EXMP, BADSYM").run(
            endpoint, [ScriptedResponse(json=body), ScriptedResponse(json={"Error Message": "Invalid API call"})]
        )
        assert result.raised is None
        assert result.params("function") == [function, function]
        assert result.params("symbol") == ["EXMP", "BADSYM"]
        assert [row["symbol"] for row in result.rows] == ["EXMP"]

    @parameterized.expand([("missing_data", {"symbol": "IBM"}), ("not_a_list", {"symbol": "IBM", "data": {}})])
    def test_parse_corporate_action_empty(self, _name: str, body: dict) -> None:
        assert list(_parse_corporate_action(body, "IBM")) == []

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

    def test_get_rows_skips_symbol_on_error_message(self) -> None:
        # An unknown ticker returns an HTTP 200 "Error Message" scoped to that symbol; the rest sync.
        result = _driver("BADSYM, AAPL").run(
            "global_quote",
            [
                ScriptedResponse(json={"Error Message": "Invalid API call"}),
                ScriptedResponse(json={"Global Quote": {"01. symbol": "AAPL", "05. price": "2"}}),
            ],
        )
        assert result.raised is None
        assert result.params("symbol") == ["BADSYM", "AAPL"]
        assert [row["symbol"] for row in result.rows] == ["AAPL"]

    def test_get_rows_propagates_permanent_quota_error(self) -> None:
        result = _driver().run("global_quote", [ScriptedResponse(json={"Information": "premium endpoint"})])
        assert isinstance(result.raised, AlphaVantageAPIError)

    def test_fetch_csv_information_envelope_is_permanent(self) -> None:
        session = _session_returning([_text_response('{"Information": "daily limit reached"}')])
        with pytest.raises(AlphaVantageAPIError) as exc:
            _fetch_csv(session, {"function": "LISTING_STATUS"})
        assert "rate_limit_or_premium" in str(exc.value)

    def test_fetch_csv_note_envelope_is_retryable(self) -> None:
        session = _session_returning([_text_response('{"Note": "call frequency limit"}')] * 5)
        with patch("time.sleep"), pytest.raises(AlphaVantageRetryableError):
            _fetch_csv(session, {"function": "LISTING_STATUS"})
        assert session.get.call_count == 5

    def test_get_rows_does_not_fan_out_the_listing_over_symbols(self) -> None:
        # LISTING_STATUS covers the whole market, so the request count must not scale with the symbols.
        result = _driver("IBM, AAPL, MSFT").run(
            "listing_status",
            [ScriptedResponse(body=b"symbol,status\nIBM,Active\n"), ScriptedResponse(json={})],
        )
        assert result.raised is None
        assert result.params("state") == list(LISTING_STATES)
        assert result.params("symbol") == [None] * len(LISTING_STATES)
        assert result.rows == [{"symbol": "IBM", "status": "Active"}]

    def test_parse_news_injects_symbol_and_keeps_the_nested_blocks(self) -> None:
        article = _article("https://news.example.com/a", "20260911T025650")
        assert list(_parse_news({"feed": [article]}, "IBM")) == [{"symbol": "IBM", **article}]

    @parameterized.expand([("missing_feed", {"items": "0"}), ("not_a_list", {"feed": {}})])
    def test_parse_news_empty(self, _name: str, body: dict) -> None:
        assert list(_parse_news(body, "IBM")) == []

    def test_parse_news_raises_when_url_missing(self) -> None:
        # `url` is a primary key; an article without one must raise rather than land unkeyed.
        with pytest.raises(KeyError):
            list(_parse_news({"feed": [{"title": "no link", "time_published": "20260911T025650"}]}, "IBM"))

    def test_parse_insider_injects_symbol_alongside_the_reported_ticker(self) -> None:
        body = {
            "data": [
                {
                    "transaction_date": "2026-08-27",
                    "ticker": "IBM",
                    "executive": "KRISHNA, ARVIND",
                    "executive_title": "Director, Chairman, President & CEO",
                    "security_type": "Phantom Stock",
                    "acquisition_or_disposal": "A",
                    "shares": "8375.5601",
                    "share_price": "238.79",
                }
            ]
        }
        assert list(_parse_insider(body, "IBM")) == [
            {
                "symbol": "IBM",
                "transaction_date": "2026-08-27",
                "ticker": "IBM",
                "executive": "KRISHNA, ARVIND",
                "executive_title": "Director, Chairman, President & CEO",
                "security_type": "Phantom Stock",
                "acquisition_or_disposal": "A",
                "shares": "8375.5601",
                "share_price": "238.79",
            }
        ]

    def test_parse_insider_nulls_placeholders(self) -> None:
        body = {"data": [{"transaction_date": "2026-08-27", "executive_title": "None"}]}
        assert list(_parse_insider(body, "IBM")) == [
            {"symbol": "IBM", "transaction_date": "2026-08-27", "executive_title": None}
        ]

    def test_parse_insider_raises_when_transaction_date_missing(self) -> None:
        with pytest.raises(KeyError):
            list(_parse_insider({"data": [{"executive": "NO DATE"}]}, "IBM"))

    @parameterized.expand([("missing_data", {}), ("not_a_list", {"data": {}})])
    def test_parse_insider_empty(self, _name: str, body: dict) -> None:
        assert list(_parse_insider(body, "IBM")) == []

    def test_parse_institutional_rides_the_symbol_totals_on_every_holder_row(self) -> None:
        # One function means one table, so dropping the symbol-level totals would lose them entirely.
        body = {
            "symbol": "IBM",
            "total_institutional_holders": "3932",
            "total_institutional_ownership_percentage": "76%",
            "holdings": [
                {"holder_name": "VANGUARD GROUP INC", "shares_held": "97216131", "last_reported": "2025-12-31"},
                {"holder_name": "BLACKROCK", "shares_held": "76763481", "last_reported": "2026-06-30"},
            ],
        }
        assert list(_parse_institutional(body, "IBM")) == [
            {
                "symbol": "IBM",
                "total_institutional_holders": "3932",
                "total_institutional_ownership_percentage": "76%",
                "holder_name": "VANGUARD GROUP INC",
                "shares_held": "97216131",
                "last_reported": "2025-12-31",
            },
            {
                "symbol": "IBM",
                "total_institutional_holders": "3932",
                "total_institutional_ownership_percentage": "76%",
                "holder_name": "BLACKROCK",
                "shares_held": "76763481",
                "last_reported": "2026-06-30",
            },
        ]

    def test_parse_institutional_raises_when_holder_name_missing(self) -> None:
        with pytest.raises(KeyError):
            list(_parse_institutional({"symbol": "IBM", "holdings": [{"shares_held": "1"}]}, "IBM"))

    @parameterized.expand([("missing_holdings", {"symbol": "IBM"}), ("not_a_list", {"holdings": {}})])
    def test_parse_institutional_empty(self, _name: str, body: dict) -> None:
        assert list(_parse_institutional(body, "IBM")) == []

    @parameterized.expand(
        [
            ("none", None, None),
            ("datetime", datetime(2026, 9, 11, 2, 56, 50, tzinfo=UTC), "20260911T0256"),
            # A watermark reaches the source as whatever the pipeline persisted, which is a string for
            # this table because `time_published` lands as the vendor's own compact format.
            ("string", "20260911T025650", "20260911T0256"),
            ("unparseable", "not a date", None),
        ]
    )
    def test_news_time_from(self, _name: str, value: Any, expected: str | None) -> None:
        assert _news_time_from(value) == expected

    @parameterized.expand(
        [
            ("full_refresh", None, False),
            ("incremental", datetime(2026, 8, 1, tzinfo=UTC), True),
        ]
    )
    def test_request_params_adds_the_insider_from_filter_only_with_a_watermark(
        self, _name: str, watermark: Any, expects_filter: bool
    ) -> None:
        params = _request_params(ALPHA_VANTAGE_ENDPOINTS["insider_transactions"], "IBM", "KEY", watermark)
        assert params["function"] == "INSIDER_TRANSACTIONS"
        if expects_filter:
            assert params["from"] == "2026-08-01"
        else:
            assert "from" not in params

    def test_news_rows_does_not_yield_the_boundary_article_twice(self) -> None:
        # Resuming from a minute re-reads every article published in it, and a merge cannot dedupe
        # within one batch sequence, so the walk has to drop what it already yielded.
        repeated = _article("https://b", "20260102T020000")
        session = _session_returning(
            [
                _news_response(_article("https://a", "20260101T010000"), repeated),
                _news_response(repeated),
            ]
        )
        with patch(f"{MODULE}.NEWS_PAGE_LIMIT", 2):
            batches = list(_news_rows(session, "KEY", "IBM", None, MagicMock()))
        assert [[row["url"] for row in batch] for batch in batches] == [["https://a", "https://b"]]

    def test_news_rows_stops_when_the_cursor_cannot_advance(self) -> None:
        # A full page that fits inside one minute would make the next request repeat it forever.
        page = _news_response(_article("https://a", "20260101T010000"), _article("https://b", "20260101T010030"))
        session = _session_returning([page, _news_response(_article("https://c", "20260101T010045"))])
        logger = MagicMock()
        with patch(f"{MODULE}.NEWS_PAGE_LIMIT", 2):
            _collect_rows(_news_rows(session, "KEY", "IBM", "20260101T0100", logger))
        assert session.get.call_count == 1
        logger.warning.assert_called_once()

    def test_news_rows_stops_on_an_unparseable_published_timestamp(self) -> None:
        session = _session_returning(
            [_news_response(_article("https://a", ""), _article("https://b", "")), _news_response()]
        )
        logger = MagicMock()
        with patch(f"{MODULE}.NEWS_PAGE_LIMIT", 2):
            rows = _collect_rows(_news_rows(session, "KEY", "IBM", None, logger))
        assert [row["url"] for row in rows] == ["https://a", "https://b"]
        assert session.get.call_count == 1
        logger.warning.assert_called_once()

    def test_news_rows_stops_at_the_page_cap(self) -> None:
        pages = [_news_response(_article(f"https://{i}", f"2026010{i}T010000")) for i in range(1, 4)]
        session = _session_returning(pages)
        logger = MagicMock()
        with patch(f"{MODULE}.NEWS_PAGE_LIMIT", 1), patch(f"{MODULE}.NEWS_MAX_PAGES", 2):
            rows = _collect_rows(_news_rows(session, "KEY", "IBM", None, logger))
        assert [row["url"] for row in rows] == ["https://1", "https://2"]
        assert session.get.call_count == 2
        logger.warning.assert_called_once()

    def test_news_rows_skips_a_symbol_on_error_message(self) -> None:
        session = _session_returning([_response(body={"Error Message": "Invalid API call"})])
        logger = MagicMock()
        assert _collect_rows(_news_rows(session, "KEY", "BADSYM", None, logger)) == []
        logger.warning.assert_called_once()

    def test_get_rows_fans_news_out_over_symbols_with_the_watermark(self) -> None:
        result = _driver("IBM, AAPL").run(
            "news_sentiment",
            [
                ScriptedResponse(json={"items": "1", "feed": [_article("https://ibm", "20260101T010000")]}),
                ScriptedResponse(json={"items": "1", "feed": [_article("https://aapl", "20260101T020000")]}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value="20251231T235900",
        )
        assert result.raised is None
        assert [(row["symbol"], row["url"]) for row in result.rows] == [
            ("IBM", "https://ibm"),
            ("AAPL", "https://aapl"),
        ]
        assert result.params("tickers") == ["IBM", "AAPL"]
        assert result.params("time_from") == ["20251231T2359", "20251231T2359"]

    def test_earnings_calendar_rows_requests_the_widest_horizon_and_chunks(self) -> None:
        header = "symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay\n"
        body = header + "".join(
            f"SYM{i},Co {i},2026-10-22,2026-09-30,1.0,USD,post-market\n" for i in range(CSV_CHUNK_SIZE + 1)
        )
        session = _session_returning([_text_response(body)])
        batches = list(_earnings_calendar_rows(session, "KEY", MagicMock()))
        assert [len(batch) for batch in batches] == [CSV_CHUNK_SIZE, 1]
        params = session.get.call_args.kwargs["params"]
        assert params["function"] == "EARNINGS_CALENDAR"
        assert params["horizon"] == EARNINGS_CALENDAR_HORIZON
        # Market-wide, so the request carries no symbol.
        assert "symbol" not in params
        assert batches[0][0] == {
            "symbol": "SYM0",
            "name": "Co 0",
            "reportDate": "2026-10-22",
            "fiscalDateEnding": "2026-09-30",
            "estimate": "1.0",
            "currency": "USD",
            "timeOfTheDay": "post-market",
        }

    def test_earnings_calendar_rows_skips_a_json_reply(self) -> None:
        session = _session_returning([_text_response("{}")])
        logger = MagicMock()
        assert _collect_rows(_earnings_calendar_rows(session, "KEY", logger)) == []
        logger.warning.assert_called_once()

    def test_get_rows_does_not_fan_out_the_earnings_calendar_over_symbols(self) -> None:
        header = "symbol,reportDate,fiscalDateEnding\n"
        result = _driver("IBM, AAPL, MSFT").run(
            "earnings_calendar", [ScriptedResponse(body=(header + "IBM,2026-10-22,2026-09-30\n").encode())]
        )
        assert result.raised is None
        assert len(result.requests) == 1
        assert result.requests[0].param("symbol") is None
        assert result.rows == [{"symbol": "IBM", "reportDate": "2026-10-22", "fiscalDateEnding": "2026-09-30"}]

    @parameterized.expand(
        [
            # Verbatim from the live API: a refused CSV function answers with the normal header and the
            # envelope key spelled one character per column, not with a JSON body.
            ("information", "Informa", AlphaVantageAPIError, "rate_limit_or_premium"),
            ("error_message", "Error M", AlphaVantageAPIError, "rate_limit_or_premium"),
            ("note", "Not", AlphaVantageRetryableError, "rate_limit"),
        ]
    )
    def test_fetch_csv_detects_an_envelope_leaked_into_the_csv_body(
        self, _name: str, leaked: str, expected_error: type[Exception], expected_marker: str
    ) -> None:
        header = "symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay"
        body = f"{header}\r\n{','.join(leaked)}\r\n"
        session = _session_returning([_text_response(body)] * 5)
        with patch("time.sleep"), pytest.raises(expected_error) as exc:
            _fetch_csv(session, {"function": "EARNINGS_CALENDAR"})
        assert expected_marker in str(exc.value)

    def test_fetch_csv_accepts_a_header_only_body(self) -> None:
        body = "symbol,name,reportDate\r\n"
        assert _fetch_csv(_session_returning([_text_response(body)]), {"function": "EARNINGS_CALENDAR"}) == body

    @parameterized.expand(
        [
            ("insider_is_newest_first", "insider_transactions", "desc"),
            ("news_restarts_per_symbol", "news_sentiment", None),
            ("full_refresh_default", "time_series_daily", "asc"),
        ]
    )
    def test_alpha_vantage_source_reports_the_order_rows_arrive_in(
        self, _name: str, endpoint: str, expected: str | None
    ) -> None:
        assert alpha_vantage_source("KEY", ["IBM"], endpoint, MagicMock()).sort_mode == expected

    @parameterized.expand(
        [
            ("time_series_daily", ["symbol", "date"], "date"),
            ("global_quote", ["symbol"], None),
            ("company_overview", ["symbol"], None),
            ("income_statement", ["symbol", "fiscalDateEnding", "report_type"], "fiscalDateEnding"),
            ("earnings", ["symbol", "fiscalDateEnding", "report_type"], "fiscalDateEnding"),
            ("news_sentiment", ["symbol", "url"], "time_published"),
            ("earnings_calendar", ["symbol", "reportDate", "fiscalDateEnding"], None),
            ("institutional_holdings", ["symbol", "holder_name", "last_reported", "shares_held"], None),
            ("shares_outstanding", ["symbol", "date"], None),
            ("earnings_estimates", ["symbol", "date", "horizon"], "date"),
            ("etf_profile", ["symbol"], None),
            ("real_gdp", ["date"], None),
            ("treasury_yield", ["maturity", "date"], "date"),
            ("federal_funds_rate", ["date"], None),
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
        ]
    )
    def test_validate_credentials(self, _name: str, api_key: str, status: int, body: dict, expected: bool) -> None:
        response = ScriptedResponse(status=status, json=body)
        script = always(response) if status >= 500 else [response]
        with scripted_network(script) as network:
            assert validate_credentials(api_key) is expected
        if api_key:
            assert network.requests_log[0].param("apikey") == api_key
        else:
            assert network.requests_log == []
