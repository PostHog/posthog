from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.finage import finage
from products.warehouse_sources.backend.temporal.data_imports.sources.finage.finage import (
    AGG_LIMIT,
    MAX_SYMBOLS,
    MIN_START_DATE,
    FinageConfigError,
    FinageRetryableError,
    finage_source,
    get_rows,
    parse_symbols,
    validate_credentials,
    validate_source_config,
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


def _http_error(status: int) -> requests.HTTPError:
    response = mock.Mock(spec=requests.Response)
    response.status_code = status
    return requests.HTTPError(response=response)


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
    def test_accepts_valid_config(self) -> None:
        # Class-share tickers with dots/hyphens are valid; a start date inside the window is fine.
        validate_source_config(["AAPL", "BRK.B", "BF-B"], "2021-06-01")

    @parameterized.expand(
        [
            ("no_symbols", [], "2021-01-01", "at least one"),
            ("too_many", [f"SYM{i}" for i in range(MAX_SYMBOLS + 1)], "2021-01-01", "Too many symbols"),
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
    def test_returns_json_on_200(self) -> None:
        session = mock.Mock()
        session.get.return_value = _response(200, {"symbol": "AAPL"})
        assert finage._fetch_json(session, "/last/stock/AAPL", "k", mock.Mock()) == {"symbol": "AAPL"}

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
        with mock.patch.object(finage, "make_tracked_session") as make_session:
            make_session.return_value.get.return_value = _response(status)
            assert validate_credentials("key") == status

    def test_returns_none_on_transport_error(self) -> None:
        with mock.patch.object(finage, "make_tracked_session") as make_session:
            make_session.return_value.get.side_effect = requests.ConnectionError()
            assert validate_credentials("key") is None


class TestGetRows:
    @parameterized.expand([("last_quote",), ("last_trade",)])
    def test_point_in_time_fans_out_per_symbol(self, endpoint: str) -> None:
        payloads = [{"symbol": "AAPL", "price": 1.0}, {"symbol": "MSFT", "price": 2.0}]
        with (
            mock.patch.object(finage, "make_tracked_session"),
            mock.patch.object(finage, "_fetch_json", side_effect=payloads),
        ):
            batches = list(get_rows("k", endpoint, ["AAPL", "MSFT"], "2020-01-01", mock.Mock()))

        # One batch (single-element list) per symbol.
        assert [row for batch in batches for row in batch] == payloads

    def test_point_in_time_pins_symbol_when_missing(self) -> None:
        with (
            mock.patch.object(finage, "make_tracked_session"),
            mock.patch.object(finage, "_fetch_json", side_effect=[{"ask": 1.0, "bid": 0.9}]),
        ):
            batches = list(get_rows("k", "last_quote", ["AAPL"], "2020-01-01", mock.Mock()))

        assert batches[0][0]["symbol"] == "AAPL"

    @parameterized.expand([("error_body", {"error": "no data"}), ("empty", {})])
    def test_point_in_time_skips_symbols_without_data(self, _name: str, bad_payload: dict) -> None:
        with (
            mock.patch.object(finage, "make_tracked_session"),
            mock.patch.object(finage, "_fetch_json", side_effect=[bad_payload, {"symbol": "MSFT", "price": 2.0}]),
        ):
            batches = list(get_rows("k", "last_trade", ["BAD", "MSFT"], "2020-01-01", mock.Mock()))

        rows = [row for batch in batches for row in batch]
        assert rows == [{"symbol": "MSFT", "price": 2.0}]

    def test_point_in_time_404_skips_but_401_propagates(self) -> None:
        # A bad ticker (404) is skipped; the next symbol still syncs.
        with (
            mock.patch.object(finage, "make_tracked_session"),
            mock.patch.object(finage, "_fetch_json", side_effect=[_http_error(404), {"symbol": "MSFT"}]),
        ):
            batches = list(get_rows("k", "last_quote", ["BAD", "MSFT"], "2020-01-01", mock.Mock()))
        assert [row for batch in batches for row in batch] == [{"symbol": "MSFT"}]

        # An auth failure (401) must fail the whole sync, not be swallowed per-symbol.
        with (
            mock.patch.object(finage, "make_tracked_session"),
            mock.patch.object(finage, "_fetch_json", side_effect=[_http_error(401)]),
        ):
            with pytest.raises(requests.HTTPError):
                list(get_rows("k", "last_quote", ["AAPL"], "2020-01-01", mock.Mock()))

    def test_aggregates_injects_symbol_and_date_and_preserves_bar(self) -> None:
        payload = {
            "symbol": "AAPL",
            "totalResults": 2,
            "results": [
                {"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100, "t": 1580860800000},
                {"o": 1.5, "h": 2.5, "l": 1, "c": 2, "v": 200, "t": 1580947200000},
            ],
        }
        with (
            mock.patch.object(finage, "make_tracked_session"),
            mock.patch.object(finage, "_fetch_json", side_effect=[payload]),
        ):
            batches = list(get_rows("k", "aggregates", ["AAPL"], "2020-02-05", mock.Mock()))

        rows = [row for batch in batches for row in batch]
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

    def test_aggregates_requests_ascending_with_limit(self) -> None:
        with (
            mock.patch.object(finage, "make_tracked_session"),
            mock.patch.object(finage, "_fetch_json", return_value={"results": []}) as fetch,
        ):
            list(get_rows("k", "aggregates", ["AAPL"], "2020-01-01", mock.Mock()))

        # sort=asc must match SourceResponse.sort_mode so the pipeline orders rows correctly.
        _args, kwargs = fetch.call_args
        assert kwargs["params"] == {"limit": AGG_LIMIT, "sort": "asc"}

    def test_aggregates_skips_symbols_with_no_results(self) -> None:
        with (
            mock.patch.object(finage, "make_tracked_session"),
            mock.patch.object(
                finage,
                "_fetch_json",
                side_effect=[{"results": []}, {"symbol": "MSFT", "results": [{"t": 1580860800000, "c": 1}]}],
            ),
        ):
            batches = list(get_rows("k", "aggregates", ["NODATA", "MSFT"], "2020-01-01", mock.Mock()))

        rows = [row for batch in batches for row in batch]
        assert len(rows) == 1
        assert rows[0]["symbol"] == "MSFT"

    @parameterized.expand([("missing_t", {"c": 1}), ("unparseable_t", {"t": "not-a-number", "c": 1})])
    def test_aggregates_rejects_bars_with_bad_timestamp(self, _name: str, bad_bar: dict) -> None:
        # `t` is the partition key. A missing key or an unparseable value would otherwise land the bar in
        # the fallback 1970-01 partition; both must fail the sync instead of silently misbucketing.
        with (
            mock.patch.object(finage, "make_tracked_session"),
            mock.patch.object(finage, "_fetch_json", side_effect=[{"symbol": "AAPL", "results": [bad_bar]}]),
        ):
            with pytest.raises((KeyError, ValueError)):
                list(get_rows("k", "aggregates", ["AAPL"], "2020-01-01", mock.Mock()))

    def test_disables_adapter_retry_so_tenacity_is_the_only_retry_layer(self) -> None:
        # The urllib3 adapter's DEFAULT_RETRY would stack on top of `_fetch_json`'s tenacity retries,
        # multiplying backoff. `get_rows` must opt the session out with retry=Retry(total=0).
        with (
            mock.patch.object(finage, "make_tracked_session") as make_session,
            mock.patch.object(finage, "_fetch_json", return_value={"results": []}),
        ):
            list(get_rows("k", "aggregates", ["AAPL"], "2020-01-01", mock.Mock()))

        _args, kwargs = make_session.call_args
        assert kwargs["retry"].total == 0


class TestFinageSourceResponse:
    @parameterized.expand(
        [
            ("last_quote", ["symbol"], None, None),
            ("last_trade", ["symbol"], None, None),
            ("aggregates", ["symbol", "t"], "datetime", ["date"]),
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
