from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.finage import finage
from products.warehouse_sources.backend.temporal.data_imports.sources.finage.finage import (
    MAX_SYMBOLS,
    MIN_START_DATE,
    STATEMENT_LIMIT,
    SYMBOL_LIST_MAX_PAGES,
    FinageConfigError,
    FinageRetryableError,
    finage_source,
    parse_symbols,
    validate_credentials,
    validate_source_config,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.finage.source import FinageSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.finage import FinageSourceConfig


def _driver(
    symbols: str = "AAPL",
    *,
    forex_symbols: str | None = None,
    crypto_symbols: str | None = None,
    start_date: str = "2020-01-01",
) -> SourceDriver:
    return SourceDriver(
        FinageSource(),
        FinageSourceConfig(
            api_key="k",
            symbols=symbols,
            forex_symbols=forex_symbols,
            crypto_symbols=crypto_symbols,
            start_date=start_date,
        ),
    )


def _response(status: int, body: dict[str, Any] | None = None) -> mock.Mock:
    response = mock.Mock(spec=requests.Response)
    response.status_code = status
    # `_fetch_json` builds its own sanitized HTTPError from these for terminal statuses.
    response.url = "https://api.finage.co.uk/x?apikey=secret"
    response.reason = "Error"
    if status >= 400:

        def _raise() -> None:
            raise requests.HTTPError(f"{status} Client Error: x for url: https://api.finage.co.uk/x", response=response)

        response.raise_for_status.side_effect = _raise
    else:
        response.raise_for_status.return_value = None
        response.json.return_value = body or {}
    return response


@pytest.fixture(autouse=True)
def _no_retry_sleep():
    # tenacity sleeps between retries; zero it so the retry tests don't actually wait.
    finage._fetch_json.retry.sleep = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    yield


class TestParseSymbols:
    @parameterized.expand(
        [
            ("simple", "AAPL,MSFT,TSLA", ["AAPL", "MSFT", "TSLA"]),
            ("whitespace", " aapl , MSFT ,  tsla ", ["AAPL", "MSFT", "TSLA"]),
            ("lowercase_upcased", "aapl", ["AAPL"]),
            ("dedupe_preserves_order", "AAPL,aapl,MSFT,AAPL", ["AAPL", "MSFT"]),
            ("trailing_commas", "AAPL,,MSFT,", ["AAPL", "MSFT"]),
            ("empty", "", []),
            ("only_separators", " , , ", []),
        ]
    )
    def test_parse_symbols(self, _name: str, raw: str, expected: list[str]) -> None:
        assert parse_symbols(raw) == expected


class TestValidateSourceConfig:
    @parameterized.expand(
        [
            ("no_symbols", [], "2021-01-01", "at least one"),
            ("too_many", [f"SYM{i}" for i in range(MAX_SYMBOLS + 1)], "2021-01-01", "Too many stock symbols"),
            ("bad_ticker", ["AAPL", "not a ticker"], "2021-01-01", "Invalid stock symbol"),
            ("malformed_date", ["AAPL"], "06/01/2021", "YYYY-MM-DD"),
            ("date_before_floor", ["AAPL"], "1990-01-01", MIN_START_DATE),
            ("future_date", ["AAPL"], "2999-01-01", "future"),
        ]
    )
    def test_rejects_invalid_config(self, _name: str, symbols: list[str], start_date: str, expected: str) -> None:
        with pytest.raises(FinageConfigError) as exc:
            validate_source_config(symbols, start_date)
        assert expected in str(exc.value)

    @parameterized.expand(
        [
            # Pair symbols carry no separators, so a stock-style ticker in the forex field is a typo
            # that would otherwise 404 every symbol at sync time.
            ("forex_ticker_shaped", {"forex_symbols": ["BRK.B"]}, "Invalid forex symbol"),
            ("forex_too_short", {"forex_symbols": ["GBP"]}, "Invalid forex symbol"),
            ("crypto_ticker_shaped", {"crypto_symbols": ["BTC-USD"]}, "Invalid crypto symbol"),
            ("forex_too_many", {"forex_symbols": [f"AAA{i:03d}" for i in range(MAX_SYMBOLS + 1)]}, "Too many forex"),
            (
                "crypto_too_many",
                {"crypto_symbols": [f"BBB{i:03d}" for i in range(MAX_SYMBOLS + 1)]},
                "Too many crypto",
            ),
        ]
    )
    def test_rejects_invalid_pair_symbols(self, _name: str, kwargs: dict, expected: str) -> None:
        with pytest.raises(FinageConfigError) as exc:
            validate_source_config(["AAPL"], "2021-01-01", **kwargs)
        assert expected in str(exc.value)


class TestMsToDate:
    @parameterized.expand(
        [
            ("epoch_millis", 1580860800000, "2020-02-05"),
            ("string_millis", "1580947200000", "2020-02-06"),
            ("none", None, None),
            ("garbage", "not-a-number", None),
        ]
    )
    def test_ms_to_date(self, _name: str, value: Any, expected: str | None) -> None:
        assert finage._ms_to_date(value) == expected


class TestFetchJson:
    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_terminal_statuses_raise_without_retry(self, _name: str, status: int) -> None:
        session = mock.Mock()
        session.get.return_value = _response(status)
        with pytest.raises(requests.HTTPError):
            finage._fetch_json(session, "/x", "k", mock.Mock())
        # Terminal statuses are surfaced immediately — never retried.
        assert session.get.call_count == 1

    def test_terminal_error_message_strips_apikey_but_keeps_matchable_prefix(self) -> None:
        response = mock.Mock(spec=requests.Response)
        response.status_code = 403
        response.reason = "Forbidden"
        response.url = (
            "https://api.finage.co.uk/agg/stock/AAPL/1/day/2020-01-01/2024-01-01?apikey=secret123&limit=50000"
        )
        session = mock.Mock()
        session.get.return_value = response
        with pytest.raises(requests.HTTPError) as exc_info:
            finage._fetch_json(session, "/agg/stock/AAPL", "secret123", mock.Mock())
        message = str(exc_info.value)
        # The raw key must never reach the error message (and thus the non-retryable error logs).
        assert "secret123" not in message
        assert "apikey" not in message
        # The prefix `get_non_retryable_errors` matches on must survive the sanitization.
        assert "403 Client Error: Forbidden for url: https://api.finage.co.uk" in message

    def test_retries_then_succeeds_on_5xx(self) -> None:
        session = mock.Mock()
        session.get.side_effect = [_response(500), _response(503), _response(200, {"ok": True})]
        assert finage._fetch_json(session, "/x", "k", mock.Mock()) == {"ok": True}
        assert session.get.call_count == 3

    def test_429_exhausts_retries(self) -> None:
        session = mock.Mock()
        session.get.side_effect = [_response(429)] * 5
        with pytest.raises(FinageRetryableError):
            finage._fetch_json(session, "/x", "k", mock.Mock())
        assert session.get.call_count == 5


class TestValidateCredentials:
    @parameterized.expand([("ok", 200), ("unauthorized", 401), ("forbidden", 403)])
    def test_returns_status_code(self, _name: str, status: int) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials("key") == status
        assert [request.path for request in network.requests_log] == ["/last/stock/AAPL"]
        assert network.requests_log[0].param("apikey") == "key"
        assert network.session_options[0]["redact_values"] == ("key",)

    def test_returns_none_on_transport_error(self) -> None:
        with scripted_network(always(requests.ConnectionError("connection reset"))) as network:
            assert validate_credentials("key") is None
        assert {request.path for request in network.requests_log} == {"/last/stock/AAPL"}


class TestGetRows:
    @parameterized.expand([("last_quote",), ("last_trade",)])
    def test_point_in_time_fans_out_per_symbol(self, endpoint: str) -> None:
        payloads = [{"symbol": "AAPL", "price": 1.0}, {"symbol": "MSFT", "price": 2.0}]
        result = _driver("AAPL,MSFT").run(endpoint, [ScriptedResponse(json=payload) for payload in payloads])

        # One batch (single-element list) per symbol.
        assert result.items == [[payload] for payload in payloads]
        assert result.rows == payloads
        path_prefix = "/last/trade/stock" if endpoint == "last_trade" else "/last/stock"
        assert result.paths == [f"{path_prefix}/{symbol}" for symbol in ("AAPL", "MSFT")]
        assert result.params("apikey") == ["k", "k"]
        assert result.raised is None

    @parameterized.expand([("error_body", {"error": "no data"}), ("empty", {})])
    def test_point_in_time_skips_symbols_without_data(self, _name: str, bad_payload: dict) -> None:
        result = _driver("BAD,MSFT").run(
            "last_trade",
            [ScriptedResponse(json=bad_payload), ScriptedResponse(json={"symbol": "MSFT", "price": 2.0})],
        )

        assert result.rows == [{"symbol": "MSFT", "price": 2.0}]
        assert result.paths == ["/last/trade/stock/BAD", "/last/trade/stock/MSFT"]
        assert result.raised is None

    def test_point_in_time_404_skips_but_401_propagates(self) -> None:
        # A bad ticker (404) is skipped; the next symbol still syncs.
        skipped = _driver("BAD,MSFT").run(
            "last_quote", [ScriptedResponse(status=404), ScriptedResponse(json={"symbol": "MSFT"})]
        )
        assert skipped.rows == [{"symbol": "MSFT"}]
        assert skipped.paths == ["/last/stock/BAD", "/last/stock/MSFT"]
        assert skipped.raised is None

        # An auth failure (401) must fail the whole sync, not be swallowed per-symbol.
        stopped = _driver().run("last_quote", [ScriptedResponse(status=401)])
        assert isinstance(stopped.raised, requests.HTTPError)
        assert stopped.paths == ["/last/stock/AAPL"]

    def test_aggregates_injects_symbol_and_date_and_preserves_bar(self) -> None:
        payload = {
            "symbol": "AAPL",
            "totalResults": 2,
            "results": [
                {"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100, "t": 1580860800000},
                {"o": 1.5, "h": 2.5, "l": 1, "c": 2, "v": 200, "t": 1580947200000},
            ],
        }
        result = _driver(start_date="2020-02-05").run("aggregates", [ScriptedResponse(json=payload)])

        rows = result.rows
        assert rows[0] == {
            "o": 1,
            "h": 2,
            "l": 0.5,
            "c": 1.5,
            "v": 100,
            "t": 1580860800000,
            "symbol": "AAPL",
            "date": "2020-02-05",
        }
        assert rows[1]["date"] == "2020-02-06"
        assert result.paths[0].startswith("/agg/stock/AAPL/1/day/2020-02-05/")
        assert result.requests[0].param("limit") == "50000"
        assert result.requests[0].param("sort") == "asc"
        assert result.raised is None

    def test_aggregates_skips_symbols_with_no_results(self) -> None:
        result = _driver("NODATA,MSFT").run(
            "aggregates",
            [
                ScriptedResponse(json={"results": []}),
                ScriptedResponse(json={"symbol": "MSFT", "results": [{"t": 1580860800000, "c": 1}]}),
            ],
        )

        assert len(result.rows) == 1
        assert result.rows[0]["symbol"] == "MSFT"
        assert len(result.requests) == 2
        assert result.raised is None

    @parameterized.expand([("missing_t", {"c": 1}), ("unparseable_t", {"t": "not-a-number", "c": 1})])
    def test_aggregates_rejects_bars_with_bad_timestamp(self, _name: str, bad_bar: dict) -> None:
        # `t` is the partition key. A missing key or an unparseable value would otherwise land the bar in
        # the fallback 1970-01 partition; both must fail the sync instead of silently misbucketing.
        result = _driver().run("aggregates", [ScriptedResponse(json={"symbol": "AAPL", "results": [bad_bar]})])
        assert isinstance(result.raised, (KeyError, ValueError))
        assert result.rows == []


class TestFundamentalsRows:
    @parameterized.expand(
        [
            ("dividends", "historical_dividends", [None]),
            ("splits", "historical_stock_splits", [None]),
            (
                "cash_flow",
                "cash_flow_statement",
                [{"limit": STATEMENT_LIMIT, "period": "annual"}, {"limit": STATEMENT_LIMIT, "period": "quarter"}],
            ),
            (
                "balance_sheet",
                "balance_sheet_statements",
                [{"limit": STATEMENT_LIMIT, "period": "annual"}, {"limit": STATEMENT_LIMIT, "period": "quarter"}],
            ),
            (
                "income_statement",
                "income_statement",
                [{"limit": STATEMENT_LIMIT, "period": "annual"}, {"limit": STATEMENT_LIMIT, "period": "quarter"}],
            ),
        ]
    )
    def test_requests_one_call_per_fiscal_period(
        self, _name: str, endpoint: str, expected_params: list[dict | None]
    ) -> None:
        # Statements default to annual, so dropping the quarter request would silently halve the table
        # while leaving it looking healthy. The dividend and split paths take no period at all.
        result = _driver().run(endpoint, [ScriptedResponse(json=[]) for _ in expected_params])

        path = finage.FINAGE_ENDPOINTS[endpoint].path.format(symbol="AAPL")
        assert result.paths == [path] * len(expected_params)
        assert [request.param("period") for request in result.requests] == [
            params["period"] if params else None for params in expected_params
        ]
        assert [request.param("limit") for request in result.requests] == [
            str(params["limit"]) if params else None for params in expected_params
        ]
        assert result.raised is None

    @parameterized.expand(
        [
            ("response_omits_symbol", {}),
            ("response_reports_another_symbol", {"symbol": "MSFT"}),
        ]
    )
    def test_pins_the_requested_symbol_onto_every_row(self, _name: str, response_symbol: dict) -> None:
        # The split and dividend responses carry no symbol, so without pinning the rows lose half
        # their primary key. A response that names a different company must not write its history
        # under that company's key either.
        record = {"numerator_factor": 4, "denominator_factor": 1, "label": "August 31, 20", "date": "2020-08-31"}
        result = _driver().run("historical_stock_splits", [ScriptedResponse(json=[{**record, **response_symbol}])])

        assert result.items == [[{**record, "symbol": "AAPL"}]]
        assert result.paths == ["/fnd/historical-stock-splits/AAPL"]
        assert result.raised is None

    @parameterized.expand(
        [
            ("missing_date", "historical_dividends", {"adj_dividend": 0.22}),
            ("malformed_date", "historical_dividends", {"date": "November 05, 21", "adj_dividend": 0.22}),
            ("calendar_without_symbol", "dividend_calendar", {"date": "2021-01-08", "adj_dividend": 0.003}),
            ("calendar_blank_symbol", "dividend_calendar", {"symbol": "   ", "date": "2021-01-08"}),
            # `strptime` parses "2021-1-8", which would key the same day two ways.
            ("noncanonical_date", "historical_dividends", {"date": "2021-1-8", "adj_dividend": 0.22}),
        ]
    )
    def test_rejects_records_that_cannot_be_keyed(self, _name: str, endpoint: str, bad_record: dict) -> None:
        # `symbol` and `date` are the primary key, and `date` is also the partition key. A bad value
        # merges unrelated rows together or buckets them into the fallback 1970-01 partition.
        result = _driver(start_date="2021-01-01").run(endpoint, [ScriptedResponse(json=[bad_record])])
        assert isinstance(result.raised, ValueError)
        assert result.rows == []

    def test_rejects_an_array_holding_something_that_is_not_a_record(self) -> None:
        # Dropping the element would let the sync finish with an incomplete table, which is the
        # outcome the key checks above exist to prevent.
        result = _driver().run(
            "historical_stock_splits", [ScriptedResponse(json=[{"date": "2020-08-31"}, "not-a-record"])]
        )
        assert isinstance(result.raised, ValueError)
        assert result.rows == []

    @parameterized.expand([("symbol_history", "historical_dividends"), ("calendar", "dividend_calendar")])
    def test_404_is_skipped_but_401_stops_the_sync(self, _name: str, endpoint: str) -> None:
        start_date = datetime.now(UTC).date().isoformat() if endpoint == "dividend_calendar" else "2021-01-01"
        skipped = _driver("BAD", start_date=start_date).run(endpoint, always(ScriptedResponse(status=404)))
        assert skipped.rows == []
        assert skipped.requests
        assert skipped.raised is None

        stopped = _driver(start_date=start_date).run(endpoint, [ScriptedResponse(status=401)])
        assert isinstance(stopped.raised, requests.HTTPError)
        assert len(stopped.requests) == 1


class TestSymbolProfileRows:
    def test_skips_a_symbol_with_no_profile_but_keeps_going(self) -> None:
        result = _driver("BAD,MSFT").run(
            "stock_details",
            [
                ScriptedResponse(json={"error": "no data"}),
                ScriptedResponse(json=[{"symbol": "MSFT", "name": "Microsoft"}]),
            ],
        )

        assert [row["symbol"] for row in result.rows] == ["MSFT"]
        assert result.paths == ["/fnd/detail/stock/BAD", "/fnd/detail/stock/MSFT"]
        assert result.raised is None


class TestSymbolListRows:
    def _page(self, *symbols: str) -> dict[str, Any]:
        return {"page": 1, "symbols": [{"symbol": s, "name": f"{s} name"} for s in symbols]}

    def test_stops_at_the_page_cap_when_the_api_never_returns_an_empty_page(self) -> None:
        # An API that ignores `page` would otherwise re-serve page one for ever and never finish.
        result = _driver().run("symbol_list", always(ScriptedResponse(json=self._page("AAPL"))))

        assert len(result.items) == SYMBOL_LIST_MAX_PAGES * 3
        assert len(result.requests) == SYMBOL_LIST_MAX_PAGES * 3
        assert result.params("page") == [str(page) for _ in range(3) for page in range(1, SYMBOL_LIST_MAX_PAGES + 1)]
        assert result.paths[0] == "/symbol-list/us-stock"
        assert result.paths[-1] == "/symbol-list/crypto"
        assert result.raised is None

    def test_rejects_an_entry_that_cannot_be_keyed(self) -> None:
        result = _driver().run("symbol_list", [ScriptedResponse(json={"symbols": [{"name": "no symbol here"}]})])
        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/symbol-list/us-stock"]

    def test_404_on_one_market_skips_it_but_401_stops_the_sync(self) -> None:
        skipped = _driver().run(
            "symbol_list",
            [
                ScriptedResponse(status=404),
                ScriptedResponse(json=self._page("GBPUSD")),
                ScriptedResponse(json={"symbols": []}),
                ScriptedResponse(json={"symbols": []}),
            ],
        )
        assert [row["market"] for row in skipped.rows] == ["forex"]
        assert skipped.paths == [
            "/symbol-list/us-stock",
            "/symbol-list/forex",
            "/symbol-list/forex",
            "/symbol-list/crypto",
        ]
        assert skipped.params("page") == ["1", "1", "2", "1"]
        assert skipped.raised is None

        stopped = _driver().run("symbol_list", [ScriptedResponse(status=401)])
        assert isinstance(stopped.raised, requests.HTTPError)
        assert stopped.paths == ["/symbol-list/us-stock"]


class TestNonEquityAssetClasses:
    @parameterized.expand(
        [
            ("forex_quote", "forex_last_quote", "/last/forex/GBPUSD"),
            ("crypto_trade", "crypto_last_trade", "/last/crypto/BTCUSD"),
        ]
    )
    def test_point_in_time_fans_out_over_its_own_symbol_list(self, _name: str, endpoint: str, path: str) -> None:
        # Fanning the stock tickers into a forex or crypto path would 404 every symbol, so the
        # endpoint must read the list that matches its asset class.
        result = _driver(forex_symbols="GBPUSD", crypto_symbols="BTCUSD").run(
            endpoint, [ScriptedResponse(json={"symbol": "X", "price": 1.0})]
        )

        assert result.paths == [path]
        assert result.rows == [{"symbol": "X", "price": 1.0}]
        assert result.raised is None

    @parameterized.expand(
        [
            ("forex_quote", "forex_last_quote"),
            ("forex_aggregates", "forex_aggregates"),
            ("crypto_trade", "crypto_last_trade"),
            ("crypto_aggregates", "crypto_aggregates"),
        ]
    )
    def test_no_configured_symbols_yields_nothing_without_calling_the_api(self, _name: str, endpoint: str) -> None:
        # The pair fields are optional, so an enabled table with an empty list must sync empty
        # rather than fall back to the stock tickers.
        result = _driver().run(endpoint, [])
        assert result.rows == []
        assert result.requests == []
        assert result.raised is None


class TestFinageSourceResponse:
    @parameterized.expand(
        [
            ("last_quote", ["symbol"], None, None),
            ("last_trade", ["symbol"], None, None),
            ("aggregates", ["symbol", "t"], "datetime", ["date"]),
            ("stock_details", ["symbol"], None, None),
            ("symbol_list", ["market", "symbol"], None, None),
            ("forex_last_quote", ["symbol"], None, None),
            ("forex_aggregates", ["symbol", "t"], "datetime", ["date"]),
            ("crypto_last_trade", ["symbol"], None, None),
            ("crypto_aggregates", ["symbol", "t"], "datetime", ["date"]),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], partition_mode: str | None, partition_keys: list[str] | None
    ) -> None:
        response = finage_source("k", endpoint, ["AAPL"], "2020-01-01", mock.Mock())
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_mode == partition_mode
        assert response.partition_keys == partition_keys
        assert response.sort_mode == "asc"
        if partition_mode == "datetime":
            assert response.partition_format == "month"
