from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.coin_api import coin_api
from products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.coin_api import (
    BASE_URL,
    CoinApiResumeConfig,
    CoinApiRetryableError,
    _format_time,
    _initial_time_start,
    _resolve_timeseries_request,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.settings import COIN_API_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.source import CoinApiSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coinapi import (
    CoinApiSourceConfig,
)


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return self._json_data

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)  # type: ignore[arg-type]


class _FakeSession:
    """Returns queued responses in order."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)

    def get(self, _url: str, **_kwargs: Any) -> _FakeResponse:
        return self._responses.pop(0)


def _driver(**config: str) -> SourceDriver:
    return SourceDriver(CoinApiSource(), CoinApiSourceConfig(api_key="key", **config))


class TestFormatTime:
    def test_date_becomes_midnight_utc(self) -> None:
        assert _format_time(date(2024, 1, 2)) == "2024-01-02T00:00:00Z"


class TestFetch:
    @parameterized.expand([(429,), (500,), (503,)])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        session = _FakeSession([_FakeResponse(status_code=status)])
        with pytest.raises(CoinApiRetryableError):
            coin_api._fetch(session, "http://x", {}, mock.MagicMock())  # type: ignore[arg-type]

    @parameterized.expand([(401,), (403,), (404,)])
    def test_client_errors_raise_http_error(self, status: int) -> None:
        session = _FakeSession([_FakeResponse(status_code=status, text="nope")])
        with pytest.raises(requests.HTTPError):
            coin_api._fetch(session, "http://x", {}, mock.MagicMock())  # type: ignore[arg-type]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("forbidden_but_genuine_key", 403, True),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("key") is expected
        assert {request.path for request in network.requests_log} == {"/v1/exchangerate/BTC/USD"}

    def test_exception_returns_false(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            assert validate_credentials("key") is False
        assert {request.path for request in network.requests_log} == {"/v1/exchangerate/BTC/USD"}

    def test_probes_exchangerate_with_key_header_and_redacts(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            assert validate_credentials("secret") is True
        assert network.requests_log[0].url == f"{BASE_URL}/v1/exchangerate/BTC/USD"
        assert network.requests_log[0].headers["x-coinapi-key"] == "secret"
        # The key rides in a custom header the sampler can't predict, so it must be redacted by value.
        assert network.session_options[0]["redact_values"] == ("secret",)


class TestInitialTimeStart:
    def test_uses_incremental_value_when_present(self) -> None:
        assert _initial_time_start(True, datetime(2024, 5, 1, tzinfo=UTC), "2020-01-01") == "2024-05-01T00:00:00Z"


class TestReferenceEndpoint:
    def test_yields_list_once_and_does_not_save_state(self) -> None:
        rows = [{"asset_id": "BTC"}, {"asset_id": "ETH"}]
        result = _driver().run("assets", [ScriptedResponse(json=rows)])
        assert result.raised is None
        assert result.items == [rows]
        assert result.saved_states == []


class TestExchangeRateEndpoint:
    def test_flattens_rates_and_injects_base(self) -> None:
        body = {
            "asset_id_base": "USD",
            "rates": [
                {"time": "2024-01-01T00:00:00Z", "asset_id_quote": "BTC", "rate": 0.00002},
                {"time": "2024-01-01T00:00:00Z", "asset_id_quote": "ETH", "rate": 0.0003},
            ],
        }
        result = _driver().run("exchange_rates", [ScriptedResponse(json=body)])
        assert result.raised is None
        assert len(result.items) == 1
        assert all(row["asset_id_base"] == "USD" for row in result.rows)
        assert {row["asset_id_quote"] for row in result.rows} == {"BTC", "ETH"}


class TestResolveTimeseriesRequest:
    @parameterized.expand(
        [
            (
                "symbol_in_path",
                "ohlcv_history",
                "/v1/ohlcv/SYM/history",
                {"period_id": "1DAY"},
                {"symbol_id": "SYM", "period_id": "1DAY"},
            ),
            (
                "symbol_in_query",
                "metrics_symbol_history",
                "/v1/metrics/symbol/history",
                {"symbol_id": "SYM", "metric_id": "FUNDING_RATE", "period_id": "1DAY"},
                {"symbol_id": "SYM", "metric_id": "FUNDING_RATE", "period_id": "1DAY"},
            ),
            (
                "assets_in_path",
                "exchange_rates_history",
                "/v1/exchangerate/USD/BTC/history",
                {"period_id": "1DAY", "time_end": "2024-06-01T00:00:00Z"},
                {"asset_id_base": "USD", "asset_id_quote": "BTC", "period_id": "1DAY"},
            ),
            (
                "no_period",
                "quotes_history",
                "/v1/quotes/SYM/history",
                {},
                {"symbol_id": "SYM"},
            ),
        ]
    )
    def test_resolves_path_params_and_row_defaults(
        self, _name: str, endpoint: str, path: str, params: dict, row_defaults: dict
    ) -> None:
        request = _resolve_timeseries_request(
            config=COIN_API_ENDPOINTS[endpoint],
            symbol_id="SYM",
            period_id="1DAY",
            metric_id="FUNDING_RATE",
            exchange_rate_base_asset="USD",
            exchange_rate_quote_asset="BTC",
            time_end="2024-06-01T00:00:00Z",
        )
        assert (request.path, request.params, request.row_defaults) == (path, params, row_defaults)


class TestTimeseriesEndpoint:
    def test_requires_symbol_id(self) -> None:
        result = _driver().run("ohlcv_history", [])
        assert isinstance(result.raised, ValueError)
        assert "requires a symbol_id" in str(result.raised)
        assert result.requests == []

    def test_requires_metric_id(self) -> None:
        result = _driver(symbol_id="SYM").run("metrics_symbol_history", [])
        assert isinstance(result.raised, ValueError)
        assert "requires a metric_id" in str(result.raised)
        assert result.requests == []

    def test_requires_quote_asset(self) -> None:
        result = _driver().run("exchange_rates_history", [])
        assert isinstance(result.raised, ValueError)
        assert "requires a quote asset" in str(result.raised)
        assert result.requests == []

    def test_exchange_rates_history_injects_both_assets(self) -> None:
        rows = [{"time_period_start": "2024-01-01T00:00:00.0000000Z", "rate_close": 1.0}]
        result = _driver(exchange_rate_base_asset="EUR", exchange_rate_quote_asset="BTC").run(
            "exchange_rates_history", [ScriptedResponse(json=rows)]
        )
        assert result.raised is None
        assert result.paths == ["/v1/exchangerate/EUR/BTC/history"]
        # CoinAPI rejects this endpoint without time_end, so every page must carry one.
        assert result.requests[0].param("time_end") is not None
        assert result.rows[0]["asset_id_base"] == "EUR"
        assert result.rows[0]["asset_id_quote"] == "BTC"

    def test_quotes_history_walks_forward_on_time_exchange(self) -> None:
        with mock.patch.object(coin_api, "PAGE_LIMIT", 1):
            page1 = [{"symbol_id": "SYM", "time_exchange": "2024-01-01T00:00:00.0000000Z", "bid_price": 1}]
            page2: list[dict] = []
            result = _driver(symbol_id="SYM", start_date="2023-01-01T00:00:00").run(
                "quotes_history", [ScriptedResponse(json=page1), ScriptedResponse(json=page2)]
            )
        assert result.raised is None
        assert result.paths == ["/v1/quotes/SYM/history", "/v1/quotes/SYM/history"]
        assert result.params("time_start") == ["2023-01-01T00:00:00", "2024-01-01T00:00:00.0000000Z"]

    def test_injects_symbol_and_period_for_ohlcv(self) -> None:
        rows = [{"time_period_start": "2024-01-01T00:00:00.0000000Z", "price_close": 1}]
        result = _driver(symbol_id="SYM").run("ohlcv_history", [ScriptedResponse(json=rows)])
        assert result.raised is None
        assert result.rows[0]["symbol_id"] == "SYM"
        assert result.rows[0]["period_id"] == "1DAY"

    def test_paginates_advancing_time_start_and_saves_state(self) -> None:
        with mock.patch.object(coin_api, "PAGE_LIMIT", 2):
            page1 = [
                {"time_period_start": "2024-01-01T00:00:00.0000000Z"},
                {"time_period_start": "2024-01-02T00:00:00.0000000Z"},
            ]
            page2 = [{"time_period_start": "2024-01-03T00:00:00.0000000Z"}]
            result = _driver(symbol_id="SYM", start_date="2023-01-01T00:00:00").run(
                "ohlcv_history", [ScriptedResponse(json=page1), ScriptedResponse(json=page2)]
            )
        assert result.raised is None
        assert len(result.items) == 2
        # Second request advances time_start to the last row of page 1.
        assert result.params("time_start") == ["2023-01-01T00:00:00", "2024-01-02T00:00:00.0000000Z"]
        # State saved once after the first full page so a crash resumes at the next window.
        assert result.saved_states == [CoinApiResumeConfig(time_start="2024-01-02T00:00:00.0000000Z")]

    def test_resumes_from_saved_time_start(self) -> None:
        rows = [{"time_period_start": "2024-06-02T00:00:00.0000000Z"}]
        result = _driver(symbol_id="SYM").run(
            "ohlcv_history",
            [ScriptedResponse(json=rows)],
            resume_state=CoinApiResumeConfig(time_start="2024-06-01T00:00:00Z"),
        )
        assert result.raised is None
        assert result.params("time_start") == ["2024-06-01T00:00:00Z"]

    def test_stall_guard_breaks_when_boundary_does_not_advance(self) -> None:
        # A full page whose rows all share one timestamp would otherwise loop forever.
        with mock.patch.object(coin_api, "PAGE_LIMIT", 2):
            same = "2024-01-01T00:00:00.0000000Z"
            page = [{"time_exchange": same, "uuid": "a"}, {"time_exchange": same, "uuid": "b"}]
            # Window start equals the page's single timestamp, so advancing wouldn't progress.
            result = _driver(symbol_id="SYM", start_date=same).run("trades_history", [ScriptedResponse(json=page)])
        assert result.raised is None
        assert len(result.items) == 1
        assert len(result.requests) == 1
        assert result.saved_states == []


class TestCoinApiSourceResponse:
    @parameterized.expand(
        [
            ("assets", ["asset_id"], False),
            ("exchanges", ["exchange_id"], False),
            ("symbols", ["symbol_id"], False),
            ("exchange_rates", ["asset_id_base", "asset_id_quote"], False),
            ("ohlcv_history", ["symbol_id", "period_id", "time_period_start"], True),
            ("trades_history", ["uuid"], True),
            ("metrics_listing", ["metric_id"], False),
            (
                "exchange_rates_history",
                ["asset_id_base", "asset_id_quote", "period_id", "time_period_start"],
                True,
            ),
            ("metrics_symbol_history", ["symbol_id", "metric_id", "period_id", "time_period_start"], True),
            (
                "quotes_history",
                ["symbol_id", "time_exchange", "time_coinapi", "ask_price", "ask_size", "bid_price", "bid_size"],
                True,
            ),
        ]
    )
    def test_primary_keys_and_partitioning(self, endpoint: str, expected_keys: list[str], partitioned: bool) -> None:
        result = _driver(symbol_id="SYM", metric_id="FUNDING_RATE", exchange_rate_quote_asset="BTC").run(
            endpoint, [ScriptedResponse(json={"rates": []} if endpoint == "exchange_rates" else [])]
        )
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == "asc"
        if partitioned:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [COIN_API_ENDPOINTS[endpoint].partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
