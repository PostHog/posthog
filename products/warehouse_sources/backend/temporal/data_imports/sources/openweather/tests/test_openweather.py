import json
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import pytest
import time_machine
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openweather import (
    OpenWeatherSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openweather.openweather import (
    MAX_LOCATIONS,
    OPENWEATHER_BASE_URL,
    Location,
    OpenWeatherRetryableError,
    TimeWindow,
    _dt_to_iso,
    _fetch,
    _normalize_rows,
    _redact_appid,
    history_windows,
    openweather_source,
    parse_locations,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openweather.settings import (
    API_VERSION_2_5,
    API_VERSION_3_0,
    API_VERSION_4_0,
    OPENWEATHER_ENDPOINTS,
    OPENWEATHER_ENDPOINTS_3_0,
    HistoryWindow,
    endpoints_for_version,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openweather.source import OpenWeatherSource

# (version, endpoint) pairs across every supported version, so the request-path dispatch is
# exercised for each.
_ALL_VERSIONED_ENDPOINTS = [
    (version, endpoint)
    for version in (API_VERSION_2_5, API_VERSION_3_0, API_VERSION_4_0)
    for endpoint in endpoints_for_version(version)
]


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

    def test_geocoding_keeps_place_coords_apart_from_requested_coords(self):
        response = [{"name": "London", "lat": 51.507, "lon": -0.127, "country": "GB", "state": "England"}]
        rows = _normalize_rows(OPENWEATHER_ENDPOINTS["geocoding"], response, Location(51.5, -0.12, "London"))

        assert rows == [
            {
                "name": "London",
                "country": "GB",
                "state": "England",
                "place_lat": 51.507,
                "place_lon": -0.127,
                "lat": 51.5,
                "lon": -0.12,
                "location_label": "London",
            }
        ]

    def test_alerts_partition_on_start(self):
        response = {"alerts": [{"sender_name": "NWS", "event": "Flood Watch", "start": 1719158400, "end": 1719169200}]}
        rows = _normalize_rows(OPENWEATHER_ENDPOINTS_3_0["alerts"], response, Location(51.5, -0.12, None))

        assert len(rows) == 1
        assert rows[0]["start_iso"] == "2024-06-23T16:00:00+00:00"
        assert "dt_iso" not in rows[0]

    def test_row_without_dt_raises(self):
        # `dt` is part of the primary key; a row missing it must fail loudly, not yield a null key.
        response = {"main": {"temp": 280}}
        with pytest.raises(KeyError):
            _normalize_rows(OPENWEATHER_ENDPOINTS["current_weather"], response, Location(51.5, -0.12, None))


_DAY = 86400


class TestHistoryWindows:
    @pytest.mark.parametrize(
        "window, start_from, end, expected",
        [
            # A watermark wins over the backfill start.
            (
                HistoryWindow(size=timedelta(days=7), lookback=timedelta(days=7)),
                10 * _DAY,
                12 * _DAY,
                [TimeWindow(start=10 * _DAY, end=12 * _DAY)],
            ),
            (
                HistoryWindow(size=timedelta(days=7), lookback=timedelta(days=7)),
                None,
                30 * _DAY,
                [TimeWindow(start=23 * _DAY, end=30 * _DAY)],
            ),
            # Consecutive windows never share a boundary second, so no row is read twice.
            (
                HistoryWindow(size=timedelta(days=2), earliest_start=datetime.fromtimestamp(0, tz=UTC)),
                None,
                5 * _DAY,
                [
                    TimeWindow(start=0, end=2 * _DAY),
                    TimeWindow(start=2 * _DAY + 1, end=4 * _DAY + 1),
                    TimeWindow(start=4 * _DAY + 2, end=5 * _DAY),
                ],
            ),
            (HistoryWindow(size=timedelta(days=7), lookback=timedelta(days=7)), 12 * _DAY + 1, 12 * _DAY, []),
        ],
    )
    def test_windows(self, window, start_from, end, expected):
        assert list(history_windows(window, start_from, end)) == expected


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
    def test_status_mapping(self, status: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            is_valid, _ = validate_credentials("test-key", "51.5,-0.12", API_VERSION_2_5)

        assert is_valid is expected_valid
        assert {request.path for request in network.requests_log} == {"/data/2.5/weather"}
        assert all(request.param("appid") == "test-key" for request in network.requests_log)

    def test_malformed_locations_is_invalid_without_request(self) -> None:
        with scripted_network([]) as network:
            is_valid, message = validate_credentials("test-key", "not-a-location", API_VERSION_2_5)

        assert is_valid is False
        assert message is not None
        assert network.requests_log == []

    def test_network_error_is_invalid(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            is_valid, message = validate_credentials("test-key", "51.5,-0.12", API_VERSION_2_5)

        assert is_valid is False
        assert message is not None
        assert {request.path for request in network.requests_log} == {"/data/2.5/weather"}


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
    def test_requests_the_pinned_versions_path(
        self, api_version: str, endpoint: str, body: dict[str, Any], expected_path: str
    ) -> None:
        # Each pin must hit its own product's paths — a wrong path 404s or bills the wrong subscription.
        driver = SourceDriver(OpenWeatherSource(), OpenWeatherSourceConfig(api_key="test-key", locations="51.5,-0.12"))
        result = driver.run(endpoint, [ScriptedResponse(json=body)], api_version=api_version)

        assert result.raised is None
        assert len(result.requests) == 1
        assert result.urls[0].startswith(f"{OPENWEATHER_BASE_URL}{expected_path}?")
        assert result.requests[0].param("appid") == "test-key"
        assert result.items[0][0]["dt"] == 1

    @pytest.mark.parametrize(
        "endpoint, should_use_incremental_field, expected_base, expected_starts, expected_type",
        [
            # Incremental: one window from the watermark to now, on the History API's own host.
            ("weather_history", True, "https://history.openweathermap.org", [1782000000], "hour"),
            # A full refresh ignores a stored watermark and reads the last week.
            ("weather_history", False, "https://history.openweathermap.org", [1782518400 - 7 * _DAY], "hour"),
            ("air_pollution_history", True, OPENWEATHER_BASE_URL, [1782000000], None),
        ],
    )
    @time_machine.travel(datetime.fromtimestamp(1782518400, tz=UTC), tick=False)
    def test_history_request_shaping(
        self,
        endpoint: str,
        should_use_incremental_field: bool,
        expected_base: str,
        expected_starts: list[int],
        expected_type: str | None,
    ) -> None:
        driver = SourceDriver(OpenWeatherSource(), OpenWeatherSourceConfig(api_key="test-key", locations="51.5,-0.12"))
        result = driver.run(
            endpoint,
            [ScriptedResponse(json={"list": [{"dt": 1782003600, "main": {"temp": 280}}]})],
            api_version=API_VERSION_2_5,
            incremental_field="dt",
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=1782000000,
        )

        assert result.raised is None
        assert all(url.startswith(f"{expected_base}/data/2.5/") for url in result.urls)
        assert [request.param("start") for request in result.requests] == [str(start) for start in expected_starts]
        assert result.requests[-1].param("end") == "1782518400"
        assert result.requests[0].param("type") == expected_type

    @time_machine.travel(datetime(2021, 1, 1, tzinfo=UTC), tick=False)
    def test_air_pollution_history_full_refresh_walks_back_to_first_data(self) -> None:
        driver = SourceDriver(OpenWeatherSource(), OpenWeatherSourceConfig(api_key="test-key", locations="51.5,-0.12"))
        result = driver.run(
            "air_pollution_history",
            always(ScriptedResponse(json={"list": [{"dt": 1609459200}]})),
            api_version=API_VERSION_2_5,
        )

        assert result.raised is None
        # 27 Nov 2020 to 1 Jan 2021 is two 30-day windows.
        assert [request.param("start") for request in result.requests] == [
            "1606435200",
            str(1606435200 + 30 * _DAY + 1),
        ]
        assert result.requests[-1].param("end") == "1609459200"


class TestOpenWeatherSource:
    @pytest.mark.parametrize("api_version, endpoint", _ALL_VERSIONED_ENDPOINTS)
    def test_source_response_shape(self, api_version, endpoint):
        config = endpoints_for_version(api_version)[endpoint]
        response = openweather_source("test-key", endpoint, "51.5,-0.12,London", structlog.get_logger(), api_version)

        assert response.name == endpoint
        assert set(config.primary_keys) >= {"lat", "lon"}
        if config.partition_key is None:
            assert response.partition_mode is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [f"{config.timestamp_field}_iso"]
        # Rows arrive per location, so no read is one ordered series.
        assert response.sort_mode is None

    def test_invalid_locations_raise(self):
        with pytest.raises(ValueError):
            openweather_source("test-key", "current_weather", "garbage", structlog.get_logger(), API_VERSION_2_5)

    def test_unsupported_version_raises(self):
        with pytest.raises(ValueError, match="Unsupported OpenWeather API version"):
            openweather_source("test-key", "current_weather", "51.5,-0.12", structlog.get_logger(), "9.9")
