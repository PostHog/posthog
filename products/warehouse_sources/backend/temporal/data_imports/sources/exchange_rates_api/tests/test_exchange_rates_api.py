from datetime import date
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api import exchange_rates_api
from products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.exchange_rates_api import (
    BASE_URL,
    DEFAULT_BASE_CURRENCY,
    MAX_RANGE_DAYS,
    ExchangeRatesApiError,
    ExchangeRatesApiResumeConfig,
    ExchangeRatesApiRetryableError,
    _build_url,
    _date_windows,
    _iter_latest,
    _iter_symbols,
    _iter_timeseries,
    _raise_on_functional_error,
    _resolve_timeseries_start,
    _to_date,
    exchange_rates_api_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.settings import (
    EXCHANGE_RATES_API_ENDPOINTS,
)


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None, text: str = "", reason: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.reason = reason
        # Mirrors requests.Response.url; the session sets it to the requested URL.
        self.url: str = ""

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
        response = self._responses.pop(0)
        response.url = url
        return response


def _manager(can_resume: bool = False, state: ExchangeRatesApiResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


class TestBuildUrl:
    def test_encodes_params_under_base_url(self) -> None:
        url = _build_url("timeseries", {"access_key": "k", "start_date": "2024-01-01", "end_date": "2024-01-02"})
        assert url == f"{BASE_URL}/timeseries?access_key=k&start_date=2024-01-01&end_date=2024-01-02"


class TestRaiseOnFunctionalError:
    def test_raises_on_success_false(self) -> None:
        body = {"success": False, "error": {"code": "invalid_base_currency", "message": "bad base"}}
        with pytest.raises(ExchangeRatesApiError) as exc:
            _raise_on_functional_error(body, "http://x")
        assert "invalid_base_currency" in str(exc.value)

    @parameterized.expand(
        [
            ("success_true", {"success": True, "rates": {}}),
            ("no_success_key", {"symbols": {}}),
            ("not_a_dict", ["a", "b"]),
        ]
    )
    def test_does_not_raise_on_valid_bodies(self, _name: str, body: Any) -> None:
        _raise_on_functional_error(body, "http://x")


class TestRequest:
    @parameterized.expand([(429,), (500,), (503,)])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        session = _FakeSession([_FakeResponse(status_code=status, json_data=None)])
        with pytest.raises(ExchangeRatesApiRetryableError):
            exchange_rates_api._request(session, "symbols", {}, mock.MagicMock())  # type: ignore[arg-type]

    def test_client_error_raises_http_error(self) -> None:
        session = _FakeSession([_FakeResponse(status_code=401, json_data=None, text="unauthorized")])
        with pytest.raises(requests.HTTPError):
            exchange_rates_api._request(session, "symbols", {}, mock.MagicMock())  # type: ignore[arg-type]

    def test_client_error_does_not_leak_access_key(self) -> None:
        # The access_key rides in the query string; a 4xx must never surface it in the raised error.
        session = _FakeSession([_FakeResponse(status_code=401, reason="Unauthorized")])
        logger = mock.MagicMock()
        with pytest.raises(requests.HTTPError) as exc:
            exchange_rates_api._request(session, "symbols", {"access_key": "SECRET_KEY"}, logger)  # type: ignore[arg-type]
        assert "SECRET_KEY" not in str(exc.value)
        assert "SECRET_KEY" not in str(logger.error.call_args)

    def test_functional_error_raises_after_200(self) -> None:
        body = {"success": False, "error": {"code": "base_currency_access_restricted", "message": "upgrade"}}
        session = _FakeSession([_FakeResponse(status_code=200, json_data=body)])
        with pytest.raises(ExchangeRatesApiError):
            exchange_rates_api._request(session, "latest", {}, mock.MagicMock())  # type: ignore[arg-type]

    def test_success_returns_parsed_body(self) -> None:
        body = {"success": True, "symbols": {"USD": "US Dollar"}}
        session = _FakeSession([_FakeResponse(status_code=200, json_data=body)])
        assert exchange_rates_api._request(session, "symbols", {}, mock.MagicMock()) == body  # type: ignore[arg-type]


class TestValidateCredentials:
    @parameterized.expand([("valid", 200, True), ("unauthorized", 401, False)])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.exchange_rates_api.make_tracked_session"
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _FakeResponse(status_code=status)
        assert validate_credentials("key") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.exchange_rates_api.make_tracked_session"
    )
    def test_exception_returns_false(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("key") is False

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.exchange_rates_api.make_tracked_session"
    )
    def test_probes_symbols_and_redacts_key(self, mock_session: mock.MagicMock) -> None:
        get = mock_session.return_value.get
        get.return_value = _FakeResponse(status_code=200)
        validate_credentials("secret")
        url = get.call_args.args[0]
        assert url.startswith(f"{BASE_URL}/symbols")
        # The key rides in a query param the sampler can't predict, so it must be redacted by value.
        assert mock_session.call_args.kwargs["redact_values"] == ("secret",)


class TestNormalization:
    def test_iter_symbols(self) -> None:
        data = {"symbols": {"USD": "US Dollar", "GBP": "Pound Sterling"}}
        assert _iter_symbols(data) == [
            {"code": "USD", "name": "US Dollar"},
            {"code": "GBP", "name": "Pound Sterling"},
        ]

    def test_iter_latest(self) -> None:
        data = {"base": "EUR", "date": "2024-01-02", "timestamp": 1704153600, "rates": {"USD": 1.1, "GBP": 0.86}}
        assert _iter_latest(data) == [
            {"base": "EUR", "currency": "USD", "rate": 1.1, "date": "2024-01-02", "timestamp": 1704153600},
            {"base": "EUR", "currency": "GBP", "rate": 0.86, "date": "2024-01-02", "timestamp": 1704153600},
        ]

    def test_iter_timeseries_sorts_by_date(self) -> None:
        data = {
            "base": "EUR",
            "rates": {"2024-01-02": {"USD": 1.2}, "2024-01-01": {"USD": 1.1}},
        }
        rows = _iter_timeseries(data)
        # Rows must arrive ascending by date to keep the incremental watermark monotonic.
        assert [r["date"] for r in rows] == ["2024-01-01", "2024-01-02"]
        assert rows[0] == {"base": "EUR", "currency": "USD", "rate": 1.1, "date": "2024-01-01"}


class TestToDate:
    @parameterized.expand(
        [
            ("iso_date", "2024-03-04", date(2024, 3, 4)),
            ("iso_datetime", "2024-03-04T12:00:00", date(2024, 3, 4)),
            ("zulu", "2024-03-04T12:00:00Z", date(2024, 3, 4)),
            ("garbage", "not-a-date", None),
            ("none", None, None),
        ]
    )
    def test_parses(self, _name: str, value: Any, expected: date | None) -> None:
        assert _to_date(value) == expected


class TestDateWindows:
    def test_single_window_when_within_max_range(self) -> None:
        windows = _date_windows(date(2024, 1, 1), date(2024, 1, 10), MAX_RANGE_DAYS)
        assert windows == [(date(2024, 1, 1), date(2024, 1, 10))]

    def test_chunks_multi_year_backfill(self) -> None:
        windows = _date_windows(date(2020, 1, 1), date(2022, 1, 1), MAX_RANGE_DAYS)
        # Each window spans at most 365 distinct days and they tile the range without gaps/overlap.
        assert len(windows) == 3
        assert windows[0][0] == date(2020, 1, 1)
        assert windows[-1][1] == date(2022, 1, 1)
        for start, end in windows:
            assert (end - start).days <= MAX_RANGE_DAYS - 1
        for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
            assert (next_start - prev_end).days == 1

    def test_empty_when_start_after_end(self) -> None:
        assert _date_windows(date(2024, 2, 1), date(2024, 1, 1), MAX_RANGE_DAYS) == []


class TestResolveTimeseriesStart:
    def test_uses_watermark_when_incremental(self) -> None:
        assert _resolve_timeseries_start(True, "2024-05-05", "2020-01-01") == date(2024, 5, 5)

    def test_uses_configured_start_when_no_watermark(self) -> None:
        assert _resolve_timeseries_start(True, None, "2020-01-01") == date(2020, 1, 1)

    def test_uses_configured_start_when_not_incremental(self) -> None:
        assert _resolve_timeseries_start(False, "2024-05-05", "2020-01-01") == date(2020, 1, 1)


class TestGetRows:
    def _run(
        self, endpoint: str, responses: list[_FakeResponse], manager: mock.MagicMock, **kwargs: Any
    ) -> tuple[list[Any], _FakeSession]:
        session = _FakeSession(responses)
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.exchange_rates_api.make_tracked_session",
            return_value=session,
        ):
            return list(get_rows("key", endpoint, "EUR", None, mock.MagicMock(), manager, **kwargs)), session

    def test_symbols_yields_once(self) -> None:
        body = {"success": True, "symbols": {"USD": "US Dollar"}}
        batches, _ = self._run("symbols", [_FakeResponse(json_data=body)], _manager())
        assert batches == [[{"code": "USD", "name": "US Dollar"}]]

    def test_symbols_empty_yields_nothing(self) -> None:
        batches, _ = self._run("symbols", [_FakeResponse(json_data={"success": True, "symbols": {}})], _manager())
        assert batches == []

    def test_latest_yields_once_and_sends_base(self) -> None:
        body = {"success": True, "base": "EUR", "date": "2024-01-02", "timestamp": 1, "rates": {"USD": 1.1}}
        batches, session = self._run("latest", [_FakeResponse(json_data=body)], _manager())
        assert batches == [[{"base": "EUR", "currency": "USD", "rate": 1.1, "date": "2024-01-02", "timestamp": 1}]]
        assert "base=EUR" in session.requested_urls[0]

    def test_timeseries_fetches_each_window_and_saves_state_between(self) -> None:
        manager = _manager()
        windows = [(date(2020, 1, 1), date(2020, 12, 30)), (date(2020, 12, 31), date(2021, 1, 5))]
        body1 = {"success": True, "base": "EUR", "rates": {"2020-01-01": {"USD": 1.1}}}
        body2 = {"success": True, "base": "EUR", "rates": {"2020-12-31": {"USD": 1.2}}}
        session = _FakeSession([_FakeResponse(json_data=body1), _FakeResponse(json_data=body2)])
        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.exchange_rates_api.make_tracked_session",
                return_value=session,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.exchange_rates_api._date_windows",
                return_value=windows,
            ),
        ):
            batches = list(
                get_rows(
                    "key",
                    "timeseries",
                    "EUR",
                    "2020-01-01",
                    mock.MagicMock(),
                    manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value="2020-01-01",
                )
            )
        assert [b[0]["date"] for b in batches] == ["2020-01-01", "2020-12-31"]
        # State is saved AFTER the first window yields (pointing at the next window), never after the last.
        manager.save_state.assert_called_once_with(ExchangeRatesApiResumeConfig(next_start_date="2020-12-31"))

    def test_timeseries_resumes_from_saved_window(self) -> None:
        manager = _manager(can_resume=True, state=ExchangeRatesApiResumeConfig(next_start_date="2020-12-31"))
        windows = [(date(2020, 1, 1), date(2020, 12, 30)), (date(2020, 12, 31), date(2021, 1, 5))]
        body2 = {"success": True, "base": "EUR", "rates": {"2020-12-31": {"USD": 1.2}}}
        session = _FakeSession([_FakeResponse(json_data=body2)])
        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.exchange_rates_api.make_tracked_session",
                return_value=session,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.exchange_rates_api._date_windows",
                return_value=windows,
            ),
        ):
            batches = list(get_rows("key", "timeseries", "EUR", "2020-01-01", mock.MagicMock(), manager))
        # Only the window at/after the resume point is fetched.
        assert len(session.requested_urls) == 1
        assert "start_date=2020-12-31" in session.requested_urls[0]
        assert [b[0]["date"] for b in batches] == ["2020-12-31"]

    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(ValueError):
            self._run("nope", [], _manager())


class TestExchangeRatesApiSource:
    @parameterized.expand(
        [
            ("symbols", ["code"]),
            ("latest", ["base", "currency", "date"]),
            ("timeseries", ["base", "currency", "date"]),
        ]
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_keys: list[str]) -> None:
        response = exchange_rates_api_source("key", endpoint, "EUR", None, mock.MagicMock(), mock.MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == "asc"

    def test_timeseries_partitions_on_stable_date(self) -> None:
        response = exchange_rates_api_source("key", "timeseries", "EUR", None, mock.MagicMock(), mock.MagicMock())
        assert response.partition_keys == ["date"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"

    def test_snapshot_endpoints_are_not_partitioned(self) -> None:
        for endpoint in ("symbols", "latest"):
            response = exchange_rates_api_source("key", endpoint, "EUR", None, mock.MagicMock(), mock.MagicMock())
            assert response.partition_keys is None

    def test_every_settings_endpoint_builds_a_source_response(self) -> None:
        for endpoint in EXCHANGE_RATES_API_ENDPOINTS:
            response = exchange_rates_api_source("key", endpoint, "EUR", None, mock.MagicMock(), mock.MagicMock())
            assert response.name == endpoint
            assert response.primary_keys == EXCHANGE_RATES_API_ENDPOINTS[endpoint].primary_keys

    def test_default_base_currency_is_eur(self) -> None:
        assert DEFAULT_BASE_CURRENCY == "EUR"
