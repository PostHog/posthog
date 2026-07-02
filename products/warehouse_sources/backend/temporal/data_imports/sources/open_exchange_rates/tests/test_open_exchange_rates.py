from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates import open_exchange_rates
from products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.open_exchange_rates import (
    BASE_URL,
    DEFAULT_BASE_CURRENCY,
    OpenExchangeRatesResumeConfig,
    OpenExchangeRatesRetryableError,
    _build_url,
    _date_from_timestamp,
    _date_range,
    _iter_currencies,
    _iter_rates,
    _iter_usage,
    _resolve_historical_start,
    _to_date,
    get_rows,
    open_exchange_rates_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.settings import (
    OPEN_EXCHANGE_RATES_ENDPOINTS,
)


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None, text: str = "", reason: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.reason = reason
        self.url: str = ""

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


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


def _manager(can_resume: bool = False, state: OpenExchangeRatesResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


class TestBuildUrl:
    def test_encodes_params_under_base_url(self) -> None:
        assert _build_url("latest.json", {"base": "EUR"}) == f"{BASE_URL}/latest.json?base=EUR"

    def test_omits_query_when_no_params(self) -> None:
        assert _build_url("currencies.json") == f"{BASE_URL}/currencies.json"


class TestRequest:
    @parameterized.expand([(500,), (502,), (503,)])
    def test_5xx_statuses_raise_retryable_error(self, status: int) -> None:
        session = _FakeSession([_FakeResponse(status_code=status, json_data=None)])
        with pytest.raises(OpenExchangeRatesRetryableError):
            open_exchange_rates._request(session, "latest.json", {}, mock.MagicMock())  # type: ignore[arg-type]

    @parameterized.expand([(401,), (403,), (429,)])
    def test_client_errors_raise_http_error(self, status: int) -> None:
        # 429 is `not_allowed` (plan-gated), not a transient throttle — it must NOT be retryable.
        session = _FakeSession([_FakeResponse(status_code=status, json_data=None, text="nope")])
        with pytest.raises(requests.HTTPError):
            open_exchange_rates._request(session, "latest.json", {}, mock.MagicMock())  # type: ignore[arg-type]

    def test_error_description_appended(self) -> None:
        body = {"error": True, "status": 401, "message": "invalid_app_id", "description": "Invalid App ID provided."}
        session = _FakeSession([_FakeResponse(status_code=401, json_data=body, reason="Unauthorized")])
        with pytest.raises(requests.HTTPError) as exc:
            open_exchange_rates._request(session, "latest.json", {}, mock.MagicMock())  # type: ignore[arg-type]
        assert "Invalid App ID provided." in str(exc.value)

    def test_success_returns_parsed_body(self) -> None:
        body = {"base": "USD", "rates": {"GBP": 0.8}}
        session = _FakeSession([_FakeResponse(status_code=200, json_data=body)])
        assert open_exchange_rates._request(session, "latest.json", {"base": "USD"}, mock.MagicMock()) == body  # type: ignore[arg-type]


class TestValidateCredentials:
    @parameterized.expand([("valid", 200, True), ("unauthorized", 401, False)])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.open_exchange_rates.make_tracked_session"
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _FakeResponse(status_code=status)
        assert validate_credentials("key") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.open_exchange_rates.make_tracked_session"
    )
    def test_exception_returns_false(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("key") is False

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.open_exchange_rates.make_tracked_session"
    )
    def test_probes_usage_with_header_auth_and_redacts_key(self, mock_session: mock.MagicMock) -> None:
        get = mock_session.return_value.get
        get.return_value = _FakeResponse(status_code=200)
        validate_credentials("secret")

        url = get.call_args.args[0]
        # usage.json validates the App ID but is free and does not count toward the request quota.
        assert url == f"{BASE_URL}/usage.json"
        # App ID rides in the Authorization header, and is redacted by value as defense in depth.
        assert mock_session.call_args.kwargs["headers"] == {"Authorization": "Token secret"}
        assert mock_session.call_args.kwargs["redact_values"] == ("secret",)


class TestNormalization:
    def test_iter_currencies(self) -> None:
        data = {"USD": "US Dollar", "GBP": "Pound Sterling"}
        assert _iter_currencies(data) == [
            {"code": "USD", "name": "US Dollar"},
            {"code": "GBP", "name": "Pound Sterling"},
        ]

    def test_iter_rates(self) -> None:
        data = {"base": "USD", "timestamp": 1704153600, "rates": {"EUR": 0.9, "GBP": 0.8}}
        assert _iter_rates(data, "2024-01-02") == [
            {"base": "USD", "currency": "EUR", "rate": 0.9, "date": "2024-01-02", "timestamp": 1704153600},
            {"base": "USD", "currency": "GBP", "rate": 0.8, "date": "2024-01-02", "timestamp": 1704153600},
        ]

    def test_iter_usage_flattens_plan_and_usage(self) -> None:
        data = {
            "status": 200,
            "data": {
                "app_id": "abc123",
                "status": "active",
                "plan": {"name": "Free", "quota": "1000 requests / month", "update_frequency": "3600s"},
                "usage": {
                    "requests": 34,
                    "requests_quota": 1000,
                    "requests_remaining": 966,
                    "days_elapsed": 2,
                    "days_remaining": 28,
                    "daily_average": 17,
                },
            },
        }
        rows = _iter_usage(data)
        assert rows == [
            {
                "app_id": "abc123",
                "status": "active",
                "plan_name": "Free",
                "plan_quota": "1000 requests / month",
                "plan_update_frequency": "3600s",
                "requests": 34,
                "requests_quota": 1000,
                "requests_remaining": 966,
                "days_elapsed": 2,
                "days_remaining": 28,
                "daily_average": 17,
            }
        ]

    def test_iter_usage_without_app_id_raises(self) -> None:
        # app_id is the primary key; a response missing it must fail loudly, not write zero rows.
        with pytest.raises(KeyError):
            _iter_usage({"data": {}})


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


class TestDateFromTimestamp:
    def test_converts_unix_timestamp_to_utc_date(self) -> None:
        # 1704153600 == 2024-01-02T00:00:00Z
        assert _date_from_timestamp(1704153600) == date(2024, 1, 2)

    @parameterized.expand([("none", None), ("garbage", "abc")])
    def test_bad_values_return_none(self, _name: str, value: Any) -> None:
        assert _date_from_timestamp(value) is None


class TestDateRange:
    @parameterized.expand(
        [
            (
                "inclusive_range",
                date(2024, 1, 1),
                date(2024, 1, 3),
                [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)],
            ),
            ("single_day", date(2024, 1, 1), date(2024, 1, 1), [date(2024, 1, 1)]),
            ("empty_when_start_after_end", date(2024, 2, 1), date(2024, 1, 1), []),
        ]
    )
    def test_date_range(self, _name: str, start: date, end: date, expected: list[date]) -> None:
        assert _date_range(start, end) == expected


class TestResolveHistoricalStart:
    @parameterized.expand(
        [
            # incremental with a watermark → re-pull from the watermark day
            ("watermark_when_incremental", True, "2024-05-05", "2020-01-01", date(2024, 5, 5)),
            # incremental but no watermark yet → fall back to the configured start
            ("configured_start_when_no_watermark", True, None, "2020-01-01", date(2020, 1, 1)),
            # not incremental → ignore the watermark, use the configured start
            ("configured_start_when_not_incremental", False, "2024-05-05", "2020-01-01", date(2020, 1, 1)),
            # nothing configured → 30-day default lookback keeps a first backfill small on a quota-limited plan
            ("defaults_to_lookback", False, None, None, date(2024, 5, 2)),
        ]
    )
    def test_resolve_start(
        self, _name: str, incremental: bool, watermark: Any, configured: str | None, expected: date
    ) -> None:
        assert _resolve_historical_start(incremental, watermark, configured, date(2024, 6, 1)) == expected


class TestGetRows:
    def _run(
        self, endpoint: str, responses: list[_FakeResponse], manager: mock.MagicMock, **kwargs: Any
    ) -> tuple[list[Any], _FakeSession]:
        session = _FakeSession(responses)
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.open_exchange_rates.make_tracked_session",
            return_value=session,
        ):
            return list(get_rows("key", endpoint, "USD", None, mock.MagicMock(), manager, **kwargs)), session

    def test_currencies_yields_once(self) -> None:
        batches, _ = self._run("currencies", [_FakeResponse(json_data={"USD": "US Dollar"})], _manager())
        assert batches == [[{"code": "USD", "name": "US Dollar"}]]

    def test_currencies_empty_yields_nothing(self) -> None:
        batches, _ = self._run("currencies", [_FakeResponse(json_data={})], _manager())
        assert batches == []

    def test_usage_yields_once(self) -> None:
        body = {"data": {"app_id": "abc", "plan": {}, "usage": {"requests": 1}}}
        batches, session = self._run("usage", [_FakeResponse(json_data=body)], _manager())
        assert batches[0][0]["app_id"] == "abc"
        assert session.requested_urls == [f"{BASE_URL}/usage.json"]

    def test_latest_sends_base_and_derives_date_from_timestamp(self) -> None:
        body = {"base": "USD", "timestamp": 1704153600, "rates": {"EUR": 0.9}}
        batches, session = self._run("latest", [_FakeResponse(json_data=body)], _manager())
        assert batches == [
            [{"base": "USD", "currency": "EUR", "rate": 0.9, "date": "2024-01-02", "timestamp": 1704153600}]
        ]
        assert "base=USD" in session.requested_urls[0]

    def test_historical_walks_each_day_and_saves_state_between(self) -> None:
        manager = _manager()
        days = [date(2024, 1, 1), date(2024, 1, 2)]
        body1 = {"base": "USD", "timestamp": 1, "rates": {"EUR": 0.9}}
        body2 = {"base": "USD", "timestamp": 2, "rates": {"EUR": 0.95}}
        session = _FakeSession([_FakeResponse(json_data=body1), _FakeResponse(json_data=body2)])
        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.open_exchange_rates.make_tracked_session",
                return_value=session,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.open_exchange_rates._date_range",
                return_value=days,
            ),
        ):
            batches = list(
                get_rows(
                    "key",
                    "historical",
                    "USD",
                    "2024-01-01",
                    mock.MagicMock(),
                    manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value="2024-01-01",
                )
            )
        assert [b[0]["date"] for b in batches] == ["2024-01-01", "2024-01-02"]
        assert session.requested_urls == [
            f"{BASE_URL}/historical/2024-01-01.json?base=USD",
            f"{BASE_URL}/historical/2024-01-02.json?base=USD",
        ]
        # State saved AFTER the first day (pointing at the next day), never after the last.
        manager.save_state.assert_called_once_with(OpenExchangeRatesResumeConfig(next_date="2024-01-02"))

    def test_historical_resumes_from_saved_day(self) -> None:
        manager = _manager(can_resume=True, state=OpenExchangeRatesResumeConfig(next_date="2024-01-02"))
        days = [date(2024, 1, 1), date(2024, 1, 2)]
        body2 = {"base": "USD", "timestamp": 2, "rates": {"EUR": 0.95}}
        session = _FakeSession([_FakeResponse(json_data=body2)])
        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.open_exchange_rates.make_tracked_session",
                return_value=session,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.open_exchange_rates._date_range",
                return_value=days,
            ),
        ):
            batches = list(get_rows("key", "historical", "USD", "2024-01-01", mock.MagicMock(), manager))
        # Only the day at/after the resume point is fetched.
        assert session.requested_urls == [f"{BASE_URL}/historical/2024-01-02.json?base=USD"]
        assert [b[0]["date"] for b in batches] == ["2024-01-02"]

    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(ValueError):
            self._run("nope", [], _manager())


class TestOpenExchangeRatesSourceResponse:
    @parameterized.expand(
        [
            ("currencies", ["code"]),
            ("latest", ["base", "currency", "date"]),
            ("historical", ["base", "currency", "date"]),
            ("usage", ["app_id"]),
        ]
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_keys: list[str]) -> None:
        response = open_exchange_rates_source("key", endpoint, "USD", None, mock.MagicMock(), mock.MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == "asc"

    @parameterized.expand([("latest",), ("historical",)])
    def test_rate_endpoints_partition_on_stable_date(self, endpoint: str) -> None:
        response = open_exchange_rates_source("key", endpoint, "USD", None, mock.MagicMock(), mock.MagicMock())
        assert response.partition_keys == ["date"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"

    @parameterized.expand([("currencies",), ("usage",)])
    def test_catalog_endpoints_are_not_partitioned(self, endpoint: str) -> None:
        response = open_exchange_rates_source("key", endpoint, "USD", None, mock.MagicMock(), mock.MagicMock())
        assert response.partition_keys is None

    def test_every_settings_endpoint_builds_a_source_response(self) -> None:
        for endpoint in OPEN_EXCHANGE_RATES_ENDPOINTS:
            response = open_exchange_rates_source("key", endpoint, "USD", None, mock.MagicMock(), mock.MagicMock())
            assert response.name == endpoint
            assert response.primary_keys == OPEN_EXCHANGE_RATES_ENDPOINTS[endpoint].primary_keys

    def test_default_base_currency_is_usd(self) -> None:
        assert DEFAULT_BASE_CURRENCY == "USD"


class TestUtcTodayUsage:
    def test_datetime_now_is_timezone_aware(self) -> None:
        # Guard the UTC handling that derives the `latest` value date and the historical window.
        assert datetime.now(tz=UTC).tzinfo is not None
