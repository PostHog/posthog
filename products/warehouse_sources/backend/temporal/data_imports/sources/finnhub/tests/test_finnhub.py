from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.finnhub import finnhub
from products.warehouse_sources.backend.temporal.data_imports.sources.finnhub.finnhub import (
    FINNHUB_BASE_URL,
    FinnhubRowCapExceededError,
    _expand_columnar,
    _extract_rows,
    _fetch,
    _parse_symbols,
    _request_params,
    _to_date,
    _window,
    finnhub_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.finnhub.settings import FINNHUB_ENDPOINTS


class TestParseSymbols:
    @parameterized.expand(
        [
            ("comma", "AAPL,MSFT", ["AAPL", "MSFT"]),
            ("comma_space", "AAPL, MSFT, GOOGL", ["AAPL", "MSFT", "GOOGL"]),
            ("lowercase_uppercased", "aapl,msft", ["AAPL", "MSFT"]),
            ("whitespace_separated", "AAPL MSFT", ["AAPL", "MSFT"]),
            ("newline_separated", "AAPL\nMSFT", ["AAPL", "MSFT"]),
            ("dedupes_preserving_order", "AAPL,MSFT,AAPL", ["AAPL", "MSFT"]),
            ("strips_blanks", "AAPL,,  ,MSFT", ["AAPL", "MSFT"]),
            ("empty_string", "", []),
            ("none", None, []),
        ]
    )
    def test_parse_symbols(self, _name: str, raw: str | None, expected: list[str]) -> None:
        assert _parse_symbols(raw) == expected

    def test_drops_oversized_tokens(self) -> None:
        # A pathologically long "symbol" is junk, not a ticker — it must not become a request.
        oversized = "A" * (finnhub.MAX_SYMBOL_LENGTH + 1)
        assert _parse_symbols(f"AAPL,{oversized},MSFT") == ["AAPL", "MSFT"]

    def test_caps_fan_out_and_warns(self) -> None:
        raw = ",".join(f"SYM{i}" for i in range(finnhub.MAX_SYMBOLS + 50))
        logger = MagicMock()
        parsed = _parse_symbols(raw, logger)
        assert len(parsed) == finnhub.MAX_SYMBOLS
        logger.warning.assert_called_once()


class TestToDate:
    @parameterized.expand(
        [
            ("epoch_seconds", 1577836800, date(2020, 1, 1)),
            ("epoch_float", 1577836800.0, date(2020, 1, 1)),
            ("aware_datetime", datetime(2021, 6, 15, 23, 0, tzinfo=UTC), date(2021, 6, 15)),
            ("naive_datetime", datetime(2021, 6, 15, 12, 0), date(2021, 6, 15)),
            ("date_passthrough", date(2022, 3, 4), date(2022, 3, 4)),
            ("iso_string", "2022-03-04T10:11:12Z", date(2022, 3, 4)),
            ("date_string", "2022-03-04", date(2022, 3, 4)),
        ]
    )
    def test_to_date(self, _name: str, value: Any, expected: date) -> None:
        assert _to_date(value) == expected


class TestExtractRows:
    def test_single_object_wraps_in_list(self) -> None:
        rows = _extract_rows({"c": 1.0}, FINNHUB_ENDPOINTS["quote"])
        assert rows == [{"c": 1.0}]

    def test_single_object_empty_returns_nothing(self) -> None:
        # Finnhub returns an empty object for an unknown symbol — that must not become a row.
        assert _extract_rows({}, FINNHUB_ENDPOINTS["quote"]) == []

    def test_data_key_unwraps_calendar(self) -> None:
        payload = {"ipoCalendar": [{"symbol": "X", "date": "2020-01-01"}]}
        assert _extract_rows(payload, FINNHUB_ENDPOINTS["ipo_calendar"]) == [{"symbol": "X", "date": "2020-01-01"}]

    def test_data_key_missing_returns_empty(self) -> None:
        assert _extract_rows({}, FINNHUB_ENDPOINTS["earnings_calendar"]) == []

    def test_bare_array_passthrough(self) -> None:
        rows = [{"symbol": "AAPL"}, {"symbol": "MSFT"}]
        assert _extract_rows(rows, FINNHUB_ENDPOINTS["stock_symbols"]) == rows

    def test_bare_array_non_list_returns_empty(self) -> None:
        assert _extract_rows({"error": "boom"}, FINNHUB_ENDPOINTS["stock_symbols"]) == []

    def test_columnar_candles_zipped_into_rows(self) -> None:
        payload = {
            "s": "ok",
            "t": [100, 200],
            "o": [1.0, 2.0],
            "h": [1.5, 2.5],
            "l": [0.5, 1.5],
            "c": [1.2, 2.2],
            "v": [10, 20],
        }
        assert _extract_rows(payload, FINNHUB_ENDPOINTS["stock_candles"]) == [
            {"t": 100, "o": 1.0, "h": 1.5, "l": 0.5, "c": 1.2, "v": 10},
            {"t": 200, "o": 2.0, "h": 2.5, "l": 1.5, "c": 2.2, "v": 20},
        ]

    @parameterized.expand(
        [
            ("no_data_status", {"s": "no_data", "t": [], "c": []}),
            ("missing_status", {"t": [100], "c": [1.0]}),
            ("no_arrays", {"s": "ok"}),
            ("not_a_dict", []),
        ]
    )
    def test_columnar_non_ok_returns_empty(self, _name: str, payload: Any) -> None:
        assert _expand_columnar(payload) == []

    def test_string_array_becomes_one_row_per_entry(self) -> None:
        # Peers come back as a bare array of tickers, not objects.
        rows = _extract_rows(["AAPL", "DELL", "HPQ"], FINNHUB_ENDPOINTS["peers"])
        assert rows == [{"peer": "AAPL"}, {"peer": "DELL"}, {"peer": "HPQ"}]

    @parameterized.expand(
        [
            ("non_string_entries", ["AAPL", 7, None], [{"peer": "AAPL"}]),
            ("blank_entries", ["AAPL", ""], [{"peer": "AAPL"}]),
            ("not_a_list", {"error": "boom"}, []),
        ]
    )
    def test_string_array_skips_unusable_entries(self, _name: str, payload: Any, expected: Any) -> None:
        assert _extract_rows(payload, FINNHUB_ENDPOINTS["peers"]) == expected

    def test_index_constituents_prefer_the_breakdown(self) -> None:
        payload = {
            "symbol": "^IBEX",
            "constituents": ["SAN.MC", "IBE.MC"],
            "constituentsBreakdown": [{"symbol": "SAN.MC", "name": "Banco Santander SA", "weight": 17.5}],
        }
        assert _extract_rows(payload, FINNHUB_ENDPOINTS["index_constituents"]) == [
            {"symbol": "SAN.MC", "name": "Banco Santander SA", "weight": 17.5}
        ]

    @parameterized.expand(
        [
            ("breakdown_absent", {"constituents": ["SAN.MC", "IBE.MC"]}),
            ("breakdown_empty", {"constituents": ["SAN.MC", "IBE.MC"], "constituentsBreakdown": []}),
        ]
    )
    def test_index_constituents_fall_back_to_the_plain_symbol_list(self, _name: str, payload: Any) -> None:
        # Plans without the breakdown still return the symbol array; it lands in the same column.
        assert _extract_rows(payload, FINNHUB_ENDPOINTS["index_constituents"]) == [
            {"symbol": "SAN.MC"},
            {"symbol": "IBE.MC"},
        ]

    def test_columnar_truncates_to_shortest_array(self) -> None:
        # A short array would otherwise leave a half-populated final row.
        payload = {"s": "ok", "t": [100, 200], "c": [1.0]}
        assert _expand_columnar(payload) == [{"t": 100, "c": 1.0}]


class TestRequestParams:
    def test_stock_symbols_defaults_exchange(self) -> None:
        params = _request_params(FINNHUB_ENDPOINTS["stock_symbols"], None, "", False, None)
        assert params == {"exchange": "US"}

    def test_stock_symbols_uses_configured_exchange(self) -> None:
        params = _request_params(FINNHUB_ENDPOINTS["stock_symbols"], None, "L", False, None)
        assert params == {"exchange": "L"}

    def test_market_news_sets_category(self) -> None:
        params = _request_params(FINNHUB_ENDPOINTS["market_news"], None, "US", False, None)
        assert params == {"category": "general"}

    def test_basic_financials_sets_metric_and_symbol(self) -> None:
        params = _request_params(FINNHUB_ENDPOINTS["basic_financials"], "AAPL", "US", False, None)
        assert params == {"symbol": "AAPL", "metric": "all"}

    @time_machine.travel("2024-06-15", tick=False)
    def test_calendar_window_is_full_rolling_window_when_not_incremental(self) -> None:
        # Calendars are full refresh: a backwards lookback plus a forward window, ignoring any cursor.
        params = _request_params(FINNHUB_ENDPOINTS["ipo_calendar"], None, "US", False, None)
        assert params == {"from": "2023-06-16", "to": "2024-12-12"}

    @time_machine.travel("2024-06-15", tick=False)
    def test_company_news_window_uses_incremental_cursor(self) -> None:
        params = _request_params(FINNHUB_ENDPOINTS["company_news"], "AAPL", "US", True, 1704067200)  # 2024-01-01
        assert params == {"symbol": "AAPL", "from": "2024-01-01", "to": "2024-06-15"}

    @time_machine.travel("2024-06-15", tick=False)
    def test_company_news_window_falls_back_to_lookback_without_cursor(self) -> None:
        params = _request_params(FINNHUB_ENDPOINTS["company_news"], "AAPL", "US", True, None)
        assert params == {"symbol": "AAPL", "from": "2023-06-16", "to": "2024-06-15"}

    @time_machine.travel("2024-06-15", tick=False)
    def test_candles_window_uses_epoch_seconds(self) -> None:
        params = _request_params(FINNHUB_ENDPOINTS["stock_candles"], "AAPL", "US", False, None)
        assert params == {"symbol": "AAPL", "resolution": "D", "from": 1655337600, "to": 1718496000}

    @time_machine.travel("2024-06-15", tick=False)
    def test_candles_window_starts_at_midnight_of_the_watermark_day(self) -> None:
        # The stored cursor is a candle timestamp mid-window; rounding down re-fetches that day.
        params = _request_params(FINNHUB_ENDPOINTS["stock_candles"], "AAPL", "US", True, 1717000000)
        assert params["from"] == 1716940800  # 2024-05-29T00:00:00Z
        assert params["to"] == 1718496000

    @time_machine.travel("2024-06-15", tick=False)
    def test_financials_reported_window_uses_long_lookback_and_freq(self) -> None:
        params = _request_params(FINNHUB_ENDPOINTS["financials_reported"], "AAPL", "US", False, None)
        assert params == {"symbol": "AAPL", "freq": "annual", "from": "2019-06-17", "to": "2024-06-15"}

    @time_machine.travel("2024-06-15", tick=False)
    def test_insider_transactions_window_uses_incremental_cursor(self) -> None:
        params = _request_params(FINNHUB_ENDPOINTS["insider_transactions"], "AAPL", "US", True, "2024-05-01")
        assert params == {"symbol": "AAPL", "from": "2024-05-01", "to": "2024-06-15"}

    @time_machine.travel("2024-06-15", tick=False)
    def test_full_refresh_omits_the_watermark(self) -> None:
        # A full refresh must sweep the whole lookback even when a cursor is stored.
        params = _request_params(FINNHUB_ENDPOINTS["sec_filings"], "AAPL", "US", False, "2024-05-01")
        assert params == {"symbol": "AAPL", "from": "2023-06-16", "to": "2024-06-15"}


class TestWindow:
    @time_machine.travel("2024-06-15", tick=False)
    def test_forward_days_extends_into_future(self) -> None:
        window = _window(FINNHUB_ENDPOINTS["earnings_calendar"], None)
        assert window.start == "2023-06-16"
        assert window.end == "2024-12-12"


class TestGetRows:
    @staticmethod
    def _patch_fetch(monkeypatch: Any, by_symbol: dict[str | None, Any]) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []

        def fake_fetch(session: Any, path: str, params: dict[str, Any], logger: Any) -> Any:
            calls.append({"path": path, "params": params})
            return by_symbol[params.get("symbol")]

        monkeypatch.setattr(finnhub, "_fetch", fake_fetch)
        monkeypatch.setattr(finnhub, "make_tracked_session", lambda **_: MagicMock())
        return calls

    def test_market_wide_endpoint_single_request(self, monkeypatch: Any) -> None:
        self._patch_fetch(monkeypatch, {None: [{"symbol": "AAPL"}, {"symbol": "MSFT"}]})
        batches = list(get_rows(api_key="k", endpoint="stock_symbols", symbols=None, exchange="US", logger=MagicMock()))
        assert batches == [[{"symbol": "AAPL"}, {"symbol": "MSFT"}]]

    def test_fan_out_one_request_per_symbol_injecting_symbol(self, monkeypatch: Any) -> None:
        calls = self._patch_fetch(
            monkeypatch,
            {"AAPL": {"c": 1.0}, "MSFT": {"c": 2.0}},
        )
        batches = list(get_rows(api_key="k", endpoint="quote", symbols="AAPL, MSFT", exchange="US", logger=MagicMock()))
        # One batch per symbol, each carrying the injected ticker (quote omits it upstream).
        assert batches == [[{"c": 1.0, "symbol": "AAPL"}], [{"c": 2.0, "symbol": "MSFT"}]]
        assert [c["params"]["symbol"] for c in calls] == ["AAPL", "MSFT"]

    def test_fan_out_skips_empty_symbol_responses(self, monkeypatch: Any) -> None:
        # Unknown ticker → empty object → no batch yielded for it.
        self._patch_fetch(monkeypatch, {"AAPL": {"c": 1.0}, "BOGUS": {}})
        batches = list(get_rows(api_key="k", endpoint="quote", symbols="AAPL,BOGUS", exchange="US", logger=MagicMock()))
        assert batches == [[{"c": 1.0, "symbol": "AAPL"}]]

    def test_requires_symbol_with_no_symbols_yields_nothing_and_warns(self, monkeypatch: Any) -> None:
        self._patch_fetch(monkeypatch, {})
        logger = MagicMock()
        batches = list(get_rows(api_key="k", endpoint="quote", symbols=None, exchange="US", logger=logger))
        assert batches == []
        logger.warning.assert_called_once()

    def test_company_news_sorted_ascending_and_symbol_injected(self, monkeypatch: Any) -> None:
        self._patch_fetch(
            monkeypatch,
            {"AAPL": [{"id": 2, "datetime": 200}, {"id": 1, "datetime": 100}]},
        )
        batches = list(
            get_rows(
                api_key="k",
                endpoint="company_news",
                symbols="AAPL",
                exchange="US",
                logger=MagicMock(),
            )
        )
        assert batches == [
            [
                {"id": 1, "datetime": 100, "symbol": "AAPL"},
                {"id": 2, "datetime": 200, "symbol": "AAPL"},
            ]
        ]

    def test_company_news_missing_datetime_raises(self, monkeypatch: Any) -> None:
        # `datetime` is the incremental watermark — a row missing it must fail loudly rather
        # than silently sorting to epoch 0 and corrupting the checkpoint.
        self._patch_fetch(monkeypatch, {"AAPL": [{"id": 1, "datetime": 100}, {"id": 2}]})
        with pytest.raises(KeyError):
            list(get_rows(api_key="k", endpoint="company_news", symbols="AAPL", exchange="US", logger=MagicMock()))

    def test_candles_emitted_as_rows_with_symbol(self, monkeypatch: Any) -> None:
        self._patch_fetch(
            monkeypatch,
            {"AAPL": {"s": "ok", "t": [200, 100], "c": [2.0, 1.0]}},
        )
        batches = list(
            get_rows(api_key="k", endpoint="stock_candles", symbols="AAPL", exchange="US", logger=MagicMock())
        )
        # Sorted ascending on the declared `t` watermark, with the requested ticker injected.
        assert batches == [[{"t": 100, "c": 1.0, "symbol": "AAPL"}, {"t": 200, "c": 2.0, "symbol": "AAPL"}]]

    def test_raises_when_a_response_hits_the_documented_cap(self, monkeypatch: Any) -> None:
        # Insider transactions cap at 100 rows per call with no pagination — a full page means
        # the API silently dropped the rest of the window. Emitting that subset would let the
        # cursor advance past the missing rows, so the sync must fail instead of checkpointing.
        rows = [{"symbol": "AAPL", "transactionDate": f"2024-01-{i % 28 + 1:02d}"} for i in range(100)]
        self._patch_fetch(monkeypatch, {"AAPL": {"data": rows}})
        logger = MagicMock()
        with pytest.raises(FinnhubRowCapExceededError):
            list(get_rows(api_key="k", endpoint="insider_transactions", symbols="AAPL", exchange="US", logger=logger))
        logger.error.assert_called_once()

    def test_no_cap_error_below_the_cap(self, monkeypatch: Any) -> None:
        rows = [{"symbol": "AAPL", "transactionDate": "2024-01-01"}]
        self._patch_fetch(monkeypatch, {"AAPL": {"data": rows}})
        logger = MagicMock()
        list(get_rows(api_key="k", endpoint="insider_transactions", symbols="AAPL", exchange="US", logger=logger))
        logger.error.assert_not_called()

    def test_peers_rows_carry_the_requested_symbol(self, monkeypatch: Any) -> None:
        self._patch_fetch(monkeypatch, {"AAPL": ["AAPL", "DELL"]})
        batches = list(get_rows(api_key="k", endpoint="peers", symbols="AAPL", exchange="US", logger=MagicMock()))
        assert batches == [[{"peer": "AAPL", "symbol": "AAPL"}, {"peer": "DELL", "symbol": "AAPL"}]]

    def test_index_constituents_fan_out_over_indices_injecting_the_index(self, monkeypatch: Any) -> None:
        calls = self._patch_fetch(
            monkeypatch,
            {"^GSPC": {"constituentsBreakdown": [{"symbol": "AAPL", "weight": 7.0}]}},
        )
        batches = list(
            get_rows(
                api_key="k",
                endpoint="index_constituents",
                symbols="MSFT",
                exchange="US",
                logger=MagicMock(),
                indices="^GSPC",
            )
        )
        # The fan-out reads Indices, not Symbols, and the constituent keeps its own `symbol`.
        assert [c["params"]["symbol"] for c in calls] == ["^GSPC"]
        assert batches == [[{"symbol": "AAPL", "weight": 7.0, "index_symbol": "^GSPC"}]]

    def test_index_constituents_with_no_indices_yields_nothing_and_warns(self, monkeypatch: Any) -> None:
        # A configured Symbols list must not be mistaken for an index list.
        self._patch_fetch(monkeypatch, {})
        logger = MagicMock()
        batches = list(
            get_rows(api_key="k", endpoint="index_constituents", symbols="AAPL", exchange="US", logger=logger)
        )
        assert batches == []
        assert "Indices" in logger.warning.call_args[0][0]

    def test_calendar_unwraps_data_key(self, monkeypatch: Any) -> None:
        self._patch_fetch(
            monkeypatch,
            {None: {"earningsCalendar": [{"symbol": "AAPL", "date": "2024-01-01"}]}},
        )
        batches = list(
            get_rows(api_key="k", endpoint="earnings_calendar", symbols=None, exchange="US", logger=MagicMock())
        )
        assert batches == [[{"symbol": "AAPL", "date": "2024-01-01"}]]


class TestFinnhubSource:
    @parameterized.expand(
        [
            ("stock_symbols", ["symbol"], None, None),
            ("market_news", ["id"], None, None),
            ("ipo_calendar", ["symbol", "date"], "date", None),
            ("earnings_calendar", ["symbol", "date"], "date", None),
            ("country", ["code2"], None, None),
            ("company_profile", ["symbol"], None, None),
            ("quote", ["symbol"], None, None),
            # Only the incremental endpoint advertises a sorted data contract.
            ("company_news", ["id", "symbol"], None, "asc"),
            ("recommendation_trends", ["symbol", "period"], "period", None),
            ("earnings_surprises", ["symbol", "period"], "period", None),
            ("financials_reported", ["symbol", "accessNumber"], "endDate", "asc"),
            ("stock_candles", ["symbol", "t"], "t", "asc"),
            ("sec_filings", ["symbol", "accessNumber"], "filedDate", "asc"),
            (
                "insider_transactions",
                [
                    "symbol",
                    "name",
                    "transactionDate",
                    "filingDate",
                    "transactionCode",
                    "change",
                    "transactionPrice",
                ],
                "transactionDate",
                "asc",
            ),
            ("dividends", ["symbol", "date", "amount"], "date", "asc"),
            ("peers", ["symbol", "peer"], None, None),
            ("index_constituents", ["index_symbol", "symbol"], None, None),
            ("economic_calendar", ["country", "event", "time"], "time", None),
        ]
    )
    def test_source_response_keys_and_partitioning(
        self, endpoint: str, expected_keys: list[str], partition_key: str | None, sort_mode: str | None
    ) -> None:
        response = finnhub_source(api_key="k", endpoint=endpoint, symbols="AAPL", exchange="US", logger=MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == sort_mode
        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
        else:
            assert response.partition_keys is None


class TestFetch:
    @staticmethod
    def _response(status_code: int, url: str, reason: str) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.reason = reason
        response.url = url
        response.text = "error body"
        return response

    def test_4xx_error_does_not_leak_api_key(self) -> None:
        # Even if the key ever lands in the request URL (redirect / future query-param auth),
        # the rebuilt HTTPError must contain only scheme/host/path — never the query string.
        session = MagicMock()
        session.get.return_value = self._response(
            401, "https://finnhub.io/api/v1/quote?token=SECRETKEY&symbol=AAPL", "Unauthorized"
        )
        with pytest.raises(requests.HTTPError) as exc:
            _fetch(session, "/quote", {"symbol": "AAPL"}, MagicMock())
        message = str(exc.value)
        assert "SECRETKEY" not in message
        assert message == "401 Client Error: Unauthorized for url: https://finnhub.io/api/v1/quote"

    def test_4xx_error_keeps_non_retryable_prefix(self) -> None:
        # get_non_retryable_errors() keys off this stable status/host prefix.
        session = MagicMock()
        session.get.return_value = self._response(403, "https://finnhub.io/api/v1/stock/metric", "Forbidden")
        with pytest.raises(requests.HTTPError) as exc:
            _fetch(session, "/stock/metric", {}, MagicMock())
        assert str(exc.value).startswith("403 Client Error: Forbidden for url: https://finnhub.io")


class TestValidateCredentials:
    @staticmethod
    def _session(status_code: int | None) -> MagicMock:
        session = MagicMock()
        if status_code is None:
            session.get.side_effect = Exception("connection refused")
        else:
            session.get.return_value = MagicMock(status_code=status_code)
        return session

    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("forbidden_at_create_is_accepted", 403, None, True),
            ("forbidden_for_schema_is_rejected", 403, "quote", False),
            ("server_error", 500, None, False),
            ("connection_error", None, None, False),
        ]
    )
    def test_validate_credentials(
        self, _name: str, status_code: int | None, schema_name: str | None, expected_valid: bool
    ) -> None:
        session = self._session(status_code)
        with patch.object(finnhub, "make_tracked_session", lambda **_: session):
            valid, _msg = validate_credentials("key", schema_name)
        assert valid is expected_valid

    def test_validate_credentials_probes_quote(self) -> None:
        session = self._session(200)
        with patch.object(finnhub, "make_tracked_session", lambda **_: session):
            validate_credentials("key")
        called_url = session.get.call_args[0][0]
        assert called_url == f"{FINNHUB_BASE_URL}/quote"


if __name__ == "__main__":
    pytest.main([__file__])
