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
    _listing_status_rows,
    _news_rows,
    _news_time_from,
    _normalize_key,
    _parse_corporate_action,
    _parse_earnings,
    _parse_insider,
    _parse_institutional,
    _parse_news,
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

    def test_parse_time_series_normalizes_the_adjusted_columns(self) -> None:
        # TIME_SERIES_DAILY_ADJUSTED rides the same parser but carries three extra ordinal-prefixed
        # columns, so the adjusted fields must land as their own snake_case columns.
        body = {
            "Meta Data": {},
            "Time Series (Daily)": {
                "2024-01-05": {
                    "1. open": "1",
                    "4. close": "1.5",
                    "5. adjusted close": "1.4",
                    "6. volume": "100",
                    "7. dividend amount": "0.0",
                    "8. split coefficient": "1.0",
                }
            },
        }
        assert list(_parse_time_series(body, "IBM")) == [
            {
                "symbol": "IBM",
                "date": "2024-01-05",
                "open": "1",
                "close": "1.5",
                "adjusted_close": "1.4",
                "volume": "100",
                "dividend_amount": "0.0",
                "split_coefficient": "1.0",
            }
        ]

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

    def test_parse_corporate_action_handles_splits_shape(self) -> None:
        body = {"symbol": "IBM", "data": [{"effective_date": "2021-11-04", "split_factor": "1.0460"}]}
        assert list(_parse_corporate_action(body, "IBM")) == [
            {"symbol": "IBM", "effective_date": "2021-11-04", "split_factor": "1.0460"}
        ]

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

    def test_fetch_csv_returns_the_csv_body(self) -> None:
        session = _session_returning([_text_response("symbol,status\nIBM,Active\n")])
        assert _fetch_csv(session, {"function": "LISTING_STATUS"}) == "symbol,status\nIBM,Active\n"

    def test_fetch_csv_returns_none_for_an_empty_json_body(self) -> None:
        # A key that is not entitled to a state gets `{}` back instead of a CSV body.
        session = _session_returning([_text_response("{}")])
        assert _fetch_csv(session, {"function": "LISTING_STATUS"}) is None

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

    def test_listing_status_rows_covers_both_states_and_nulls_placeholders(self) -> None:
        active = "symbol,name,exchange,assetType,ipoDate,delistingDate,status\nIBM,IBM Corp,NYSE,Stock,1962-01-02,null,Active\n"
        delisted = "symbol,name,exchange,assetType,ipoDate,delistingDate,status\nOLD,Old Co,NYSE,Stock,1998-01-02,2014-07-10,Delisted\n"
        session = _session_returning([_text_response(active), _text_response(delisted)])
        rows = _collect_rows(_listing_status_rows(session, "KEY", MagicMock()))
        assert [session.get.call_args_list[i].kwargs["params"]["state"] for i in range(2)] == ["active", "delisted"]
        assert rows == [
            {
                "symbol": "IBM",
                "name": "IBM Corp",
                "exchange": "NYSE",
                "assetType": "Stock",
                "ipoDate": "1962-01-02",
                # The vendor writes "null" rather than leaving the cell empty.
                "delistingDate": None,
                "status": "Active",
            },
            {
                "symbol": "OLD",
                "name": "Old Co",
                "exchange": "NYSE",
                "assetType": "Stock",
                "ipoDate": "1998-01-02",
                "delistingDate": "2014-07-10",
                "status": "Delisted",
            },
        ]

    def test_listing_status_rows_skips_a_state_with_no_csv(self) -> None:
        active = "symbol,status\nIBM,Active\n"
        session = _session_returning([_text_response(active), _text_response("{}")])
        logger = MagicMock()
        rows = _collect_rows(_listing_status_rows(session, "KEY", logger))
        assert [r["symbol"] for r in rows] == ["IBM"]
        logger.warning.assert_called_once()

    def test_listing_status_rows_chunks_large_listings(self) -> None:
        header = "symbol,status\n"
        body = header + "".join(f"SYM{i},Active\n" for i in range(CSV_CHUNK_SIZE + 1))
        session = _session_returning([_text_response(body), _text_response("{}")])
        batches = list(_listing_status_rows(session, "KEY", MagicMock()))
        assert [len(batch) for batch in batches] == [CSV_CHUNK_SIZE, 1]

    def test_get_rows_does_not_fan_out_the_listing_over_symbols(self) -> None:
        # LISTING_STATUS covers the whole market, so the request count must not scale with the symbols.
        responses = [_text_response("symbol,status\nIBM,Active\n"), _text_response("{}")]
        session = _session_returning(responses)
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            rows = _collect_rows(get_rows("KEY", ["IBM", "AAPL", "MSFT"], "listing_status", MagicMock()))
        assert session.get.call_count == len(LISTING_STATES)
        assert rows == [{"symbol": "IBM", "status": "Active"}]

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

    def test_request_params_ignores_a_watermark_for_a_full_refresh_function(self) -> None:
        # Only INSIDER_TRANSACTIONS takes a server-side date bound; sending one elsewhere would be
        # silently ignored by the API and misleading to a reader.
        params = _request_params(
            ALPHA_VANTAGE_ENDPOINTS["global_quote"], "IBM", "KEY", datetime(2026, 8, 1, tzinfo=UTC)
        )
        assert "from" not in params

    def test_news_rows_stops_on_a_short_page(self) -> None:
        session = _session_returning([_news_response(_article("https://a", "20260101T010000"))])
        with patch(f"{MODULE}.NEWS_PAGE_LIMIT", 2):
            rows = _collect_rows(_news_rows(session, "KEY", "IBM", None, MagicMock()))
        assert [row["url"] for row in rows] == ["https://a"]
        assert session.get.call_count == 1
        params = session.get.call_args.kwargs["params"]
        assert params["tickers"] == "IBM"
        # Oldest-first, so the watermark advances monotonically and the walk can resume from the end.
        assert params["sort"] == "EARLIEST"
        assert "time_from" not in params

    def test_news_rows_walks_forward_from_the_last_article_of_a_full_page(self) -> None:
        session = _session_returning(
            [
                _news_response(_article("https://a", "20260101T010000"), _article("https://b", "20260102T020000")),
                _news_response(_article("https://c", "20260103T030000")),
            ]
        )
        with patch(f"{MODULE}.NEWS_PAGE_LIMIT", 2):
            rows = _collect_rows(_news_rows(session, "KEY", "IBM", None, MagicMock()))
        assert [row["url"] for row in rows] == ["https://a", "https://b", "https://c"]
        # `time_from` is minute-granular, so the second page resumes from the last article's minute.
        assert session.get.call_args_list[1].kwargs["params"]["time_from"] == "20260102T0200"

    def test_news_rows_passes_through_the_starting_watermark(self) -> None:
        session = _session_returning([_news_response(_article("https://a", "20260101T010000"))])
        with patch(f"{MODULE}.NEWS_PAGE_LIMIT", 2):
            _collect_rows(_news_rows(session, "KEY", "IBM", "20251231T2359", MagicMock()))
        assert session.get.call_args.kwargs["params"]["time_from"] == "20251231T2359"

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
        responses = [
            _news_response(_article("https://ibm", "20260101T010000")),
            _news_response(_article("https://aapl", "20260101T020000")),
        ]
        session = _session_returning(responses)
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            rows = _collect_rows(get_rows("KEY", ["IBM", "AAPL"], "news_sentiment", MagicMock(), "20251231T235900"))
        assert [(row["symbol"], row["url"]) for row in rows] == [("IBM", "https://ibm"), ("AAPL", "https://aapl")]
        assert [call.kwargs["params"]["tickers"] for call in session.get.call_args_list] == ["IBM", "AAPL"]
        assert all(call.kwargs["params"]["time_from"] == "20251231T2359" for call in session.get.call_args_list)

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
        session = _session_returning([_text_response(header + "IBM,2026-10-22,2026-09-30\n")])
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            rows = _collect_rows(get_rows("KEY", ["IBM", "AAPL", "MSFT"], "earnings_calendar", MagicMock()))
        assert session.get.call_count == 1
        assert rows == [{"symbol": "IBM", "reportDate": "2026-10-22", "fiscalDateEnding": "2026-09-30"}]

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

    def test_fetch_csv_accepts_a_real_data_row(self) -> None:
        body = "symbol,name,reportDate\r\nIBM,International Business Machines,2026-10-22\r\n"
        assert _fetch_csv(_session_returning([_text_response(body)]), {"function": "EARNINGS_CALENDAR"}) == body

    def test_fetch_csv_accepts_a_header_only_body(self) -> None:
        body = "symbol,name,reportDate\r\n"
        assert _fetch_csv(_session_returning([_text_response(body)]), {"function": "EARNINGS_CALENDAR"}) == body

    @parameterized.expand(
        [
            ("insider_is_newest_first", "insider_transactions", "desc"),
            ("news_is_oldest_first", "news_sentiment", "asc"),
            ("full_refresh_default", "time_series_daily", "asc"),
        ]
    )
    def test_alpha_vantage_source_reports_the_order_rows_arrive_in(
        self, _name: str, endpoint: str, expected: str
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
