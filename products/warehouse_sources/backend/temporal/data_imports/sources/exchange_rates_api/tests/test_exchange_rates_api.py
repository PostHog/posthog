from datetime import date, timedelta
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api import exchange_rates_api
from products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.exchange_rates_api import (
    BASE_URL,
    MAX_RANGE_DAYS,
    ExchangeRatesApiError,
    ExchangeRatesApiResumeConfig,
    ExchangeRatesApiRetryableError,
    _date_windows,
    _raise_on_functional_error,
    _to_date,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.source import (
    ExchangeRatesApiSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.exchangeratesapi import (
    ExchangeRatesApiSourceConfig,
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


class TestValidateCredentials:
    def test_probes_symbols_and_redacts_key(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("secret") is True
        assert network.requests_log[0].url.startswith(f"{BASE_URL}/symbols")
        assert network.requests_log[0].param("access_key") == "secret"
        # The key rides in a query param the sampler can't predict, so it must be redacted by value.
        assert network.session_options[0]["redact_values"] == ("secret",)


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


class TestGetRows:
    @staticmethod
    def _driver(start_date: str | None = None) -> SourceDriver:
        return SourceDriver(
            ExchangeRatesApiSource(),
            ExchangeRatesApiSourceConfig(access_key="key", base_currency="EUR", start_date=start_date),
        )

    def _run(
        self, endpoint: str, responses: list[_FakeResponse], manager: mock.MagicMock, **kwargs: Any
    ) -> tuple[list[Any], _FakeSession]:
        session = _FakeSession(responses)
        return list(get_rows("key", endpoint, "EUR", None, mock.MagicMock(), manager, **kwargs)), session

    def test_symbols_yields_once(self) -> None:
        body = {"success": True, "symbols": {"USD": "US Dollar"}}
        result = self._driver().run("symbols", [ScriptedResponse(json=body)])
        assert result.raised is None
        assert result.items == [[{"code": "USD", "name": "US Dollar"}]]

    def test_latest_yields_once_and_sends_base(self) -> None:
        body = {"success": True, "base": "EUR", "date": "2024-01-02", "timestamp": 1, "rates": {"USD": 1.1}}
        result = self._driver().run("latest", [ScriptedResponse(json=body)])
        assert result.raised is None
        assert result.items == [[{"base": "EUR", "currency": "USD", "rate": 1.1, "date": "2024-01-02", "timestamp": 1}]]
        assert result.requests[0].param("base") == "EUR"

    def test_timeseries_fetches_each_window_and_saves_state_between(self) -> None:
        today = date.today()
        first_day = today - timedelta(days=MAX_RANGE_DAYS)
        body1 = {"success": True, "base": "EUR", "rates": {first_day.isoformat(): {"USD": 1.1}}}
        body2 = {"success": True, "base": "EUR", "rates": {today.isoformat(): {"USD": 1.2}}}
        result = self._driver(first_day.isoformat()).run(
            "timeseries",
            [ScriptedResponse(json=body1), ScriptedResponse(json=body2)],
            incremental_field="date",
            db_incremental_field_last_value=first_day.isoformat(),
        )
        assert result.raised is None
        assert result.params("start_date") == [first_day.isoformat(), today.isoformat()]
        assert [batch[0]["date"] for batch in result.items] == [first_day.isoformat(), today.isoformat()]
        # State is saved AFTER the first window yields (pointing at the next window), never after the last.
        assert result.saved_states == [ExchangeRatesApiResumeConfig(next_start_date=today.isoformat())]

    def test_timeseries_resumes_from_saved_window(self) -> None:
        today = date.today()
        first_day = today - timedelta(days=MAX_RANGE_DAYS)
        body2 = {"success": True, "base": "EUR", "rates": {today.isoformat(): {"USD": 1.2}}}
        result = self._driver(first_day.isoformat()).run(
            "timeseries",
            [ScriptedResponse(json=body2)],
            resume_state=ExchangeRatesApiResumeConfig(next_start_date=today.isoformat()),
        )
        # Only the window at/after the resume point is fetched.
        assert result.raised is None
        assert result.params("start_date") == [today.isoformat()]
        assert [batch[0]["date"] for batch in result.items] == [today.isoformat()]

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
        body = (
            {"symbols": {}} if endpoint == "symbols" else {"base": "EUR", "date": date.today().isoformat(), "rates": {}}
        )
        result = SourceDriver(
            ExchangeRatesApiSource(),
            ExchangeRatesApiSourceConfig(access_key="key", base_currency="EUR", start_date=date.today().isoformat()),
        ).run(endpoint, [ScriptedResponse(json=body)])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == "asc"
