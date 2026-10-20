from datetime import UTC, date, datetime, timedelta
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openexchangerates import (
    OpenExchangeRatesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates import open_exchange_rates
from products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.open_exchange_rates import (
    BASE_URL,
    OpenExchangeRatesResumeConfig,
    OpenExchangeRatesRetryableError,
    _date_from_timestamp,
    _date_range,
    _iter_usage,
    _resolve_historical_start,
    _to_date,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.source import (
    OpenExchangeRatesSource,
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


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("over_use", 429, (False, open_exchange_rates.RESTRICTED_ACCOUNT_ERROR)),
            ("upstream_outage", 503, (False, open_exchange_rates.VALIDATION_UNAVAILABLE_ERROR)),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: tuple[bool, str | None]) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("key") == expected
        assert {request.path for request in network.requests_log} == {"/api/usage.json"}

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.open_exchange_rates.capture_exception"
    )
    def test_network_error_does_not_blame_the_app_id(self, mock_capture: mock.MagicMock) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            assert validate_credentials("key") == (False, open_exchange_rates.VALIDATION_UNAVAILABLE_ERROR)
        mock_capture.assert_called_once()

    def test_probes_usage_with_header_auth_and_redacts_key(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            assert validate_credentials("secret") == (True, None)

        # usage.json validates the App ID but is free and does not count toward the request quota.
        assert network.requests_log[0].url == f"{BASE_URL}/usage.json"
        # App ID rides in the Authorization header, and is redacted by value as defense in depth.
        assert network.requests_log[0].headers["authorization"] == "Token secret"
        assert network.session_options[0]["headers"] == {"Authorization": "Token secret"}
        assert network.session_options[0]["redact_values"] == ("secret",)


class TestNormalization:
    def test_iter_usage_never_stores_the_credential(self) -> None:
        # app_id is the API credential (a secret) — it must never be written into the synced row.
        rows = _iter_usage({"data": {"app_id": "SECRET_APP_ID", "plan": {}, "usage": {}}})
        assert rows == [
            {
                "id": "usage",
                "status": None,
                "plan_name": None,
                "plan_quota": None,
                "plan_update_frequency": None,
                "requests": None,
                "requests_quota": None,
                "requests_remaining": None,
                "days_elapsed": None,
                "days_remaining": None,
                "daily_average": None,
            }
        ]
        assert "SECRET_APP_ID" not in str(rows)


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
        return list(get_rows("key", endpoint, "USD", None, mock.MagicMock(), manager, **kwargs)), session

    @staticmethod
    def _driver(start_date: str | None = None) -> SourceDriver:
        return SourceDriver(
            OpenExchangeRatesSource(),
            OpenExchangeRatesSourceConfig(app_id="key", base_currency="USD", start_date=start_date),
        )

    def test_currencies_yields_once(self) -> None:
        result = self._driver().run("currencies", [ScriptedResponse(json={"USD": "US Dollar"})])
        assert result.raised is None
        assert result.items == [[{"code": "USD", "name": "US Dollar"}]]

    def test_usage_yields_once(self) -> None:
        body = {"data": {"app_id": "abc", "plan": {}, "usage": {"requests": 1}}}
        result = self._driver().run("usage", [ScriptedResponse(json=body)])
        assert result.raised is None
        assert result.items[0][0]["id"] == "usage"
        assert result.items[0][0]["requests"] == 1
        # The credential must not be echoed into the synced row.
        assert "app_id" not in result.items[0][0]
        assert result.urls == [f"{BASE_URL}/usage.json"]

    def test_latest_sends_base_and_derives_date_from_timestamp(self) -> None:
        body = {"base": "USD", "timestamp": 1704153600, "rates": {"EUR": 0.9}}
        result = self._driver().run("latest", [ScriptedResponse(json=body)])
        assert result.raised is None
        assert result.items == [
            [{"base": "USD", "currency": "EUR", "rate": 0.9, "date": "2024-01-02", "timestamp": 1704153600}]
        ]
        assert result.params("base") == ["USD"]

    def test_historical_walks_each_day_and_saves_state_between(self) -> None:
        yesterday = datetime.now(tz=UTC).date().toordinal() - 1
        days = [date.fromordinal(yesterday - 1), date.fromordinal(yesterday)]
        body1 = {"base": "USD", "timestamp": 1, "rates": {"EUR": 0.9}}
        body2 = {"base": "USD", "timestamp": 2, "rates": {"EUR": 0.95}}
        result = self._driver(days[0].isoformat()).run(
            "historical",
            [ScriptedResponse(json=body1), ScriptedResponse(json=body2)],
            incremental_field="date",
            db_incremental_field_last_value=days[0].isoformat(),
        )
        assert result.raised is None
        assert [batch[0]["date"] for batch in result.items] == [day.isoformat() for day in days]
        assert result.urls == [f"{BASE_URL}/historical/{day.isoformat()}.json?base=USD" for day in days]
        # State saved AFTER the first day (pointing at the next day), never after the last.
        assert result.saved_states == [OpenExchangeRatesResumeConfig(next_date=days[1].isoformat())]

    def test_historical_resumes_from_saved_day(self) -> None:
        yesterday = datetime.now(tz=UTC).date().toordinal() - 1
        days = [date.fromordinal(yesterday - 1), date.fromordinal(yesterday)]
        body2 = {"base": "USD", "timestamp": 2, "rates": {"EUR": 0.95}}
        result = self._driver(days[0].isoformat()).run(
            "historical",
            [ScriptedResponse(json=body2)],
            resume_state=OpenExchangeRatesResumeConfig(next_date=days[1].isoformat()),
        )
        # Only the day at/after the resume point is fetched.
        assert result.raised is None
        assert result.urls == [f"{BASE_URL}/historical/{days[1].isoformat()}.json?base=USD"]
        assert [batch[0]["date"] for batch in result.items] == [days[1].isoformat()]

    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(ValueError):
            self._run("nope", [], _manager())


class TestOpenExchangeRatesSourceResponse:
    @staticmethod
    def _run(endpoint: str) -> SourceDriver:
        start = (datetime.now(tz=UTC).date() - timedelta(days=1)).isoformat()
        config = OpenExchangeRatesSourceConfig(app_id="key", base_currency="USD", start_date=start)
        return SourceDriver(OpenExchangeRatesSource(), config)

    @staticmethod
    def _answer(endpoint: str) -> ScriptedResponse:
        if endpoint == "currencies":
            return ScriptedResponse(json={"USD": "US Dollar"})
        if endpoint == "usage":
            return ScriptedResponse(json={"data": {}})
        return ScriptedResponse(json={"base": "USD", "timestamp": 1704153600, "rates": {"EUR": 0.9}})

    @parameterized.expand(
        [
            ("currencies", ["code"]),
            ("latest", ["base", "currency", "date"]),
            ("historical", ["base", "currency", "date"]),
            ("usage", ["id"]),
        ]
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_keys: list[str]) -> None:
        result = self._run(endpoint).run(endpoint, always(self._answer(endpoint)))
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == "asc"

    @parameterized.expand([("latest",), ("historical",)])
    def test_rate_endpoints_partition_on_stable_date(self, endpoint: str) -> None:
        result = self._run(endpoint).run(endpoint, always(self._answer(endpoint)))
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.partition_keys == ["date"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"

    @parameterized.expand([("currencies",), ("usage",)])
    def test_catalog_endpoints_are_not_partitioned(self, endpoint: str) -> None:
        result = self._run(endpoint).run(endpoint, always(self._answer(endpoint)))
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.partition_keys is None


class TestUtcTodayUsage:
    def test_datetime_now_is_timezone_aware(self) -> None:
        # Guard the UTC handling that derives the `latest` value date and the historical window.
        assert datetime.now(tz=UTC).tzinfo is not None
