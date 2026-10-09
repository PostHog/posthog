import json
from typing import Any, Optional

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.openweather.openweather import (
    MAX_LOCATIONS,
    OPENWEATHER_BASE_URL,
    Location,
    OpenWeatherRetryableError,
    _dt_to_iso,
    _fetch,
    _normalize_rows,
    _redact_appid,
    get_rows,
    openweather_source,
    parse_locations,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openweather.settings import (
    API_VERSION_2_5,
    API_VERSION_3_0,
    API_VERSION_4_0,
    OPENWEATHER_ENDPOINTS,
    endpoints_for_version,
)

# (version, endpoint) pairs across every supported version, so the request-path dispatch is
# exercised for each.
_ALL_VERSIONED_ENDPOINTS = [
    (version, endpoint)
    for version in (API_VERSION_2_5, API_VERSION_3_0, API_VERSION_4_0)
    for endpoint in endpoints_for_version(version)
]

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.openweather.openweather"


def _response(status: int = 200, body: Optional[dict[str, Any]] = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = body or {}
    resp.text = json.dumps(body or {})
    if not resp.ok:
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"{status} Client Error for url: {OPENWEATHER_BASE_URL}", response=requests.Response()
        )
    return resp


class TestParseLocations:
    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "   \n  ",
            "51.5",  # missing longitude
            "abc,def",  # non-numeric
            "91,0",  # latitude out of range
            "0,181",  # longitude out of range
        ],
    )
    def test_invalid_raises(self, raw):
        with pytest.raises(ValueError):
            parse_locations(raw)

    def test_rejects_too_many_locations(self):
        raw = "\n".join(f"{i % 90},0" for i in range(MAX_LOCATIONS + 1))
        with pytest.raises(ValueError, match="Too many locations"):
            parse_locations(raw)


class TestDtToIso:
    @pytest.mark.parametrize(
        "dt, expected",
        [
            (1719158400, "2024-06-23T16:00:00+00:00"),
            (1719158400.0, "2024-06-23T16:00:00+00:00"),
            (None, None),
            ("not-a-number", None),
        ],
    )
    def test_dt_to_iso(self, dt, expected):
        assert _dt_to_iso(dt) == expected


class TestRedactAppid:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("https://x/?lat=1&appid=secret", "https://x/?lat=1&appid=REDACTED"),
            ("https://x/?appid=secret&lat=1", "https://x/?appid=REDACTED&lat=1"),
            ("APPID=secret", "APPID=REDACTED"),  # case-insensitive
            ("no key here", "no key here"),
        ],
    )
    def test_redact(self, text, expected):
        assert _redact_appid(text) == expected


class TestNormalizeRows:
    def test_current_weather_injects_requested_coords(self):
        # The API echoes coord snapped to the nearest station; we keep the *requested* coords on the row.
        response = {"coord": {"lat": 51.51, "lon": -0.13}, "main": {"temp": 280}, "dt": 1719158400, "name": "London"}
        rows = _normalize_rows(OPENWEATHER_ENDPOINTS["current_weather"], response, Location(51.5, -0.12, "London"))

        assert len(rows) == 1
        row = rows[0]
        assert row["lat"] == 51.5
        assert row["lon"] == -0.12
        assert row["location_label"] == "London"
        assert row["dt_iso"] == "2024-06-23T16:00:00+00:00"
        assert row["main"] == {"temp": 280}

    def test_forecast_yields_one_row_per_slot_with_city(self):
        response = {
            "list": [{"dt": 1719158400, "main": {"temp": 280}}, {"dt": 1719169200, "main": {"temp": 281}}],
            "city": {"id": 1, "name": "London"},
        }
        rows = _normalize_rows(OPENWEATHER_ENDPOINTS["forecast"], response, Location(51.5, -0.12, None))

        assert [row["dt"] for row in rows] == [1719158400, 1719169200]
        assert all(row["city"] == {"id": 1, "name": "London"} for row in rows)
        assert all(row["lat"] == 51.5 and row["lon"] == -0.12 for row in rows)

    def test_row_without_dt_raises(self):
        # `dt` is part of the primary key; a row missing it must fail loudly, not yield a null key.
        response = {"main": {"temp": 280}}
        with pytest.raises(KeyError):
            _normalize_rows(OPENWEATHER_ENDPOINTS["current_weather"], response, Location(51.5, -0.12, None))


# The undecorated `_fetch` (tenacity exposes the original via `__wrapped__`) so the status
# classification can be asserted without waiting through retry backoff.
_fetch_once = _fetch.__wrapped__  # type: ignore[attr-defined]


class TestFetch:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable(self, status):
        session = mock.MagicMock()
        session.get.return_value = _response(status)

        with pytest.raises(OpenWeatherRetryableError):
            _fetch_once(session, "https://example.com", structlog.get_logger())

    def test_client_error_raises_for_status(self):
        session = mock.MagicMock()
        session.get.return_value = _response(404)

        with pytest.raises(requests.HTTPError):
            _fetch_once(session, "https://example.com", structlog.get_logger())

    def test_error_message_redacts_appid(self):
        # The API key is passed as `appid`, so the raise_for_status URL must not leak it into the error.
        resp = mock.MagicMock()
        resp.status_code = 401
        resp.ok = False
        resp.text = '{"cod":401,"message":"Invalid API key."}'
        resp.raise_for_status.side_effect = requests.HTTPError(
            "401 Client Error: Unauthorized for url: "
            "https://api.openweathermap.org/data/2.5/weather?lat=51.5&lon=-0.12&appid=SUPERSECRETKEY",
            response=requests.Response(),
        )
        session = mock.MagicMock()
        session.get.return_value = resp

        with pytest.raises(requests.HTTPError) as exc_info:
            _fetch_once(session, "https://example.com", structlog.get_logger())

        message = str(exc_info.value)
        assert "SUPERSECRETKEY" not in message
        assert "appid=REDACTED" in message
        # The host prefix is preserved so non-retryable-error matching still works.
        assert "for url: https://api.openweathermap.org" in message


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid",
        [
            (200, True),
            (401, False),
            (500, False),
        ],
    )
    def test_status_mapping(self, status, expected_valid):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(status)

            is_valid, _ = validate_credentials("test-key", "51.5,-0.12", API_VERSION_2_5)

        assert is_valid is expected_valid

    def test_malformed_locations_is_invalid_without_request(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            is_valid, message = validate_credentials("test-key", "not-a-location", API_VERSION_2_5)

        assert is_valid is False
        assert message is not None
        mock_session.return_value.get.assert_not_called()

    def test_network_error_is_invalid(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")

            is_valid, message = validate_credentials("test-key", "51.5,-0.12", API_VERSION_2_5)

        assert is_valid is False
        assert message is not None


class TestGetRows:
    @pytest.mark.parametrize(
        "api_version, endpoint, body, expected_path",
        [
            (API_VERSION_2_5, "current_weather", {"dt": 1, "main": {"temp": 280}}, "/data/2.5/weather"),
            (API_VERSION_3_0, "current", {"current": {"dt": 1, "temp": 280}}, "/data/3.0/onecall"),
            (API_VERSION_4_0, "current", {"data": [{"dt": 1, "temp": 280}]}, "/data/4.0/onecall/current"),
            (API_VERSION_4_0, "minutely", {"data": [{"dt": 1, "precipitation": 0}]}, "/data/4.0/onecall/timeline/1min"),
            (
                API_VERSION_4_0,
                "quarter_hourly",
                {"data": [{"dt": 1, "temp": 280}]},
                "/data/4.0/onecall/timeline/15min",
            ),
            (API_VERSION_4_0, "hourly", {"data": [{"dt": 1, "temp": 280}]}, "/data/4.0/onecall/timeline/1h"),
            (API_VERSION_4_0, "daily", {"data": [{"dt": 1, "temp": {"day": 280}}]}, "/data/4.0/onecall/timeline/1day"),
        ],
    )
    def test_requests_the_pinned_versions_path(self, api_version, endpoint, body, expected_path):
        # Each pin must hit its own product's paths — a wrong path 404s or bills the wrong subscription.
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200, body)

            batches = list(
                get_rows("test-key", endpoint, [Location(51.5, -0.12, None)], structlog.get_logger(), api_version)
            )

            called_url = mock_session.return_value.get.call_args[0][0]

        assert called_url.startswith(f"{OPENWEATHER_BASE_URL}{expected_path}?")
        assert batches[0][0]["dt"] == 1


class TestOpenWeatherSource:
    @pytest.mark.parametrize("api_version, endpoint", _ALL_VERSIONED_ENDPOINTS)
    def test_source_response_shape(self, api_version, endpoint):
        response = openweather_source("test-key", endpoint, "51.5,-0.12,London", structlog.get_logger(), api_version)

        assert response.name == endpoint
        assert response.primary_keys == ["lat", "lon", "dt"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["dt_iso"]
        assert response.sort_mode == "asc"

    def test_invalid_locations_raise(self):
        with pytest.raises(ValueError):
            openweather_source("test-key", "current_weather", "garbage", structlog.get_logger(), API_VERSION_2_5)

    def test_unsupported_version_raises(self):
        with pytest.raises(ValueError, match="Unsupported OpenWeather API version"):
            openweather_source("test-key", "current_weather", "51.5,-0.12", structlog.get_logger(), "9.9")
