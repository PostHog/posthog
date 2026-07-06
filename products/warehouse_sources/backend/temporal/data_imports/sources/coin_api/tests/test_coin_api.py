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
    _build_url,
    _format_time,
    _headers,
    _initial_time_start,
    coin_api_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.settings import COIN_API_ENDPOINTS


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)  # type: ignore[arg-type]


class _FakeSession:
    """Returns queued responses in order; records the URLs requested."""

    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.requested_urls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.requested_urls.append(url)
        return self._responses.pop(0)


def _manager(can_resume: bool = False, state: CoinApiResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


def _run(
    endpoint: str, responses: list[_FakeResponse], manager: mock.MagicMock, **kwargs: Any
) -> tuple[list[list[dict]], _FakeSession]:
    session = _FakeSession(responses)
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.coin_api.make_tracked_session",
        return_value=session,
    ):
        return list(get_rows("key", endpoint, mock.MagicMock(), manager, **kwargs)), session


class TestHeadersAndUrl:
    def test_headers_include_key(self) -> None:
        headers = _headers("secret-key")
        assert headers["X-CoinAPI-Key"] == "secret-key"
        assert headers["Accept"] == "application/json"

    def test_headers_omit_key_when_blank(self) -> None:
        assert "X-CoinAPI-Key" not in _headers("")

    def test_build_url_without_params(self) -> None:
        assert _build_url("/v1/assets", {}) == f"{BASE_URL}/v1/assets"

    def test_build_url_encodes_params(self) -> None:
        url = _build_url("/v1/ohlcv/SYM/history", {"period_id": "1DAY", "limit": 100})
        assert url == f"{BASE_URL}/v1/ohlcv/SYM/history?period_id=1DAY&limit=100"


class TestFormatTime:
    def test_naive_datetime_gets_z_suffix(self) -> None:
        assert _format_time(datetime(2024, 1, 2, 3, 4, 5)) == "2024-01-02T03:04:05Z"

    def test_aware_datetime_converted_to_utc(self) -> None:
        assert _format_time(datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)) == "2024-01-02T03:04:05Z"

    def test_date_becomes_midnight_utc(self) -> None:
        assert _format_time(date(2024, 1, 2)) == "2024-01-02T00:00:00Z"

    def test_string_passthrough(self) -> None:
        assert _format_time("2024-01-02T00:00:00") == "2024-01-02T00:00:00"


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

    def test_ok_returns_json(self) -> None:
        session = _FakeSession([_FakeResponse(json_data=[{"a": 1}])])
        assert coin_api._fetch(session, "http://x", {}, mock.MagicMock()) == [{"a": 1}]  # type: ignore[arg-type]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, True),
            ("forbidden_but_genuine_key", 403, True),
            ("unauthorized", 401, False),
            ("server_error", 500, False),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.coin_api.make_tracked_session"
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _FakeResponse(status_code=status)
        assert validate_credentials("key") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.coin_api.make_tracked_session"
    )
    def test_exception_returns_false(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("key") is False

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.coin_api.make_tracked_session"
    )
    def test_probes_exchangerate_with_key_header_and_redacts(self, mock_session: mock.MagicMock) -> None:
        get = mock_session.return_value.get
        get.return_value = _FakeResponse(status_code=200)
        validate_credentials("secret")
        assert get.call_args.args[0] == f"{BASE_URL}/v1/exchangerate/BTC/USD"
        assert get.call_args.kwargs["headers"]["X-CoinAPI-Key"] == "secret"
        # The key rides in a custom header the sampler can't predict, so it must be redacted by value.
        assert mock_session.call_args.kwargs["redact_values"] == ("secret",)


class TestInitialTimeStart:
    def test_uses_incremental_value_when_present(self) -> None:
        assert _initial_time_start(True, datetime(2024, 5, 1, tzinfo=UTC), "2020-01-01") == "2024-05-01T00:00:00Z"

    def test_falls_back_to_start_date_when_no_incremental_value(self) -> None:
        assert _initial_time_start(False, None, "2020-01-01") == "2020-01-01"

    def test_defaults_to_lookback_when_nothing_provided(self) -> None:
        # Just assert it produces a Z-suffixed ISO string rather than pinning to a wall-clock value.
        result = _initial_time_start(False, None, "")
        assert result.endswith("Z")


class TestReferenceEndpoint:
    def test_yields_list_once_and_does_not_save_state(self) -> None:
        manager = _manager()
        rows = [{"asset_id": "BTC"}, {"asset_id": "ETH"}]
        batches, _ = _run("assets", [_FakeResponse(json_data=rows)], manager)
        assert batches == [rows]
        manager.save_state.assert_not_called()

    def test_empty_yields_nothing(self) -> None:
        batches, _ = _run("assets", [_FakeResponse(json_data=[])], _manager())
        assert batches == []


class TestExchangeRateEndpoint:
    def test_flattens_rates_and_injects_base(self) -> None:
        body = {
            "asset_id_base": "USD",
            "rates": [
                {"time": "2024-01-01T00:00:00Z", "asset_id_quote": "BTC", "rate": 0.00002},
                {"time": "2024-01-01T00:00:00Z", "asset_id_quote": "ETH", "rate": 0.0003},
            ],
        }
        batches, session = _run("exchange_rates", [_FakeResponse(json_data=body)], _manager())
        assert len(batches) == 1
        assert all(row["asset_id_base"] == "USD" for row in batches[0])
        assert {row["asset_id_quote"] for row in batches[0]} == {"BTC", "ETH"}

    def test_uses_configured_base_in_path(self) -> None:
        body = {"asset_id_base": "EUR", "rates": []}
        _, session = _run("exchange_rates", [_FakeResponse(json_data=body)], _manager(), exchange_rate_base_asset="EUR")
        assert session.requested_urls[0] == f"{BASE_URL}/v1/exchangerate/EUR"


class TestTimeseriesEndpoint:
    def test_requires_symbol_id(self) -> None:
        with pytest.raises(ValueError, match="requires a symbol_id"):
            _run("ohlcv_history", [], _manager(), symbol_id="")

    def test_injects_symbol_and_period_for_ohlcv(self) -> None:
        with mock.patch.object(coin_api, "PAGE_LIMIT", 5):
            rows = [{"time_period_start": "2024-01-01T00:00:00.0000000Z", "price_close": 1}]
            batches, _ = _run("ohlcv_history", [_FakeResponse(json_data=rows)], _manager(), symbol_id="SYM")
        assert batches[0][0]["symbol_id"] == "SYM"
        assert batches[0][0]["period_id"] == "1DAY"

    def test_paginates_advancing_time_start_and_saves_state(self) -> None:
        with mock.patch.object(coin_api, "PAGE_LIMIT", 2):
            page1 = [
                {"time_period_start": "2024-01-01T00:00:00.0000000Z"},
                {"time_period_start": "2024-01-02T00:00:00.0000000Z"},
            ]
            page2 = [{"time_period_start": "2024-01-03T00:00:00.0000000Z"}]
            manager = _manager()
            batches, session = _run(
                "ohlcv_history",
                [_FakeResponse(json_data=page1), _FakeResponse(json_data=page2)],
                manager,
                symbol_id="SYM",
                start_date="2023-01-01T00:00:00",
            )
        assert len(batches) == 2
        # Second request advances time_start to the last row of page 1.
        assert "time_start=2024-01-02T00%3A00%3A00.0000000Z" in session.requested_urls[1]
        # State saved once after the first full page so a crash resumes at the next window.
        manager.save_state.assert_called_once_with(CoinApiResumeConfig(time_start="2024-01-02T00:00:00.0000000Z"))

    def test_short_first_page_stops_without_second_request(self) -> None:
        with mock.patch.object(coin_api, "PAGE_LIMIT", 5):
            rows = [{"time_period_start": "2024-01-01T00:00:00.0000000Z"}]
            manager = _manager()
            batches, session = _run("ohlcv_history", [_FakeResponse(json_data=rows)], manager, symbol_id="SYM")
        assert len(batches) == 1
        assert len(session.requested_urls) == 1
        manager.save_state.assert_not_called()

    def test_resumes_from_saved_time_start(self) -> None:
        with mock.patch.object(coin_api, "PAGE_LIMIT", 5):
            manager = _manager(can_resume=True, state=CoinApiResumeConfig(time_start="2024-06-01T00:00:00Z"))
            rows = [{"time_period_start": "2024-06-02T00:00:00.0000000Z"}]
            _, session = _run("ohlcv_history", [_FakeResponse(json_data=rows)], manager, symbol_id="SYM")
        assert "time_start=2024-06-01T00%3A00%3A00Z" in session.requested_urls[0]

    def test_uses_incremental_value_as_initial_time_start(self) -> None:
        with mock.patch.object(coin_api, "PAGE_LIMIT", 5):
            rows = [{"time_exchange": "2024-05-02T00:00:00.0000000Z", "uuid": "u1"}]
            _, session = _run(
                "trades_history",
                [_FakeResponse(json_data=rows)],
                _manager(),
                symbol_id="SYM",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
            )
        assert "time_start=2024-05-01T00%3A00%3A00Z" in session.requested_urls[0]

    def test_stall_guard_breaks_when_boundary_does_not_advance(self) -> None:
        # A full page whose rows all share one timestamp would otherwise loop forever.
        with mock.patch.object(coin_api, "PAGE_LIMIT", 2):
            same = "2024-01-01T00:00:00.0000000Z"
            page = [{"time_exchange": same, "uuid": "a"}, {"time_exchange": same, "uuid": "b"}]
            manager = _manager()
            # Window start equals the page's single timestamp, so advancing wouldn't progress.
            batches, session = _run(
                "trades_history", [_FakeResponse(json_data=page)], manager, symbol_id="SYM", start_date=same
            )
        assert len(batches) == 1
        assert len(session.requested_urls) == 1
        manager.save_state.assert_not_called()


class TestCoinApiSourceResponse:
    @parameterized.expand(
        [
            ("assets", ["asset_id"], False),
            ("exchanges", ["exchange_id"], False),
            ("symbols", ["symbol_id"], False),
            ("exchange_rates", ["asset_id_base", "asset_id_quote"], False),
            ("ohlcv_history", ["symbol_id", "period_id", "time_period_start"], True),
            ("trades_history", ["uuid"], True),
        ]
    )
    def test_primary_keys_and_partitioning(self, endpoint: str, expected_keys: list[str], partitioned: bool) -> None:
        response = coin_api_source("key", endpoint, mock.MagicMock(), mock.MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == "asc"
        if partitioned:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [COIN_API_ENDPOINTS[endpoint].partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_every_settings_endpoint_builds_a_source_response(self) -> None:
        for endpoint in COIN_API_ENDPOINTS:
            response = coin_api_source("key", endpoint, mock.MagicMock(), mock.MagicMock())
            assert response.name == endpoint
            assert response.primary_keys == COIN_API_ENDPOINTS[endpoint].primary_keys
