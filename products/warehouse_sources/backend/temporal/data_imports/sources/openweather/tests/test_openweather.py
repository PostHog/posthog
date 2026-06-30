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
    _build_url,
    _dt_to_iso,
    _fetch,
    _normalize_rows,
    _redact_appid,
    get_rows,
    openweather_source,
    parse_locations,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openweather.settings import OPENWEATHER_ENDPOINTS

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
        "raw, expected",
        [
            ("51.5,-0.12", [Location(51.5, -0.12, None)]),
            ("51.5,-0.12,London", [Location(51.5, -0.12, "London")]),
            ("  51.5 , -0.12 , London  ", [Location(51.5, -0.12, "London")]),
            ("51.5,-0.12,London\n40.7,-74.0", [Location(51.5, -0.12, "London"), Location(40.7, -74.0, None)]),
            ("51.5,-0.12\n\n  \n40.7,-74.0", [Location(51.5, -0.12, None), Location(40.7, -74.0, None)]),
            # Labels containing commas are preserved.
            ("40.7,-74.0,New York, NY", [Location(40.7, -74.0, "New York, NY")]),
        ],
    )
    def test_valid(self, raw, expected):
        assert parse_locations(raw) == expected

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

    def test_allows_max_locations(self):
        raw = "\n".join(f"{i % 90},0" for i in range(MAX_LOCATIONS))
        assert len(parse_locations(raw)) == MAX_LOCATIONS


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


class TestBuildUrl:
    def test_includes_coords_and_appid(self):
        url = _build_url("/data/2.5/weather", {"lat": 51.5, "lon": -0.12, "appid": "secret-key"})

        assert url.startswith(f"{OPENWEATHER_BASE_URL}/data/2.5/weather?")
        assert "lat=51.5" in url
        assert "lon=-0.12" in url
        assert "appid=secret-key" in url


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

    def test_air_pollution_list_rows(self):
        response = {"coord": {"lat": 51.5, "lon": -0.12}, "list": [{"main": {"aqi": 2}, "dt": 1719158400}]}
        rows = _normalize_rows(OPENWEATHER_ENDPOINTS["air_pollution"], response, Location(51.5, -0.12, None))

        assert len(rows) == 1
        assert rows[0]["main"] == {"aqi": 2}
        assert rows[0]["dt_iso"] == "2024-06-23T16:00:00+00:00"

    def test_row_without_dt_raises(self):
        # `dt` is part of the primary key; a row missing it must fail loudly, not yield a null key.
        response = {"main": {"temp": 280}}
        with pytest.raises(KeyError):
            _normalize_rows(OPENWEATHER_ENDPOINTS["current_weather"], response, Location(51.5, -0.12, None))


# The undecorated `_fetch` (tenacity exposes the original via `__wrapped__`) so the status
# classification can be asserted without waiting through retry backoff.
_fetch_once = _fetch.__wrapped__  # type: ignore[attr-defined]


class TestFetch:
    def test_ok_returns_body(self):
        session = mock.MagicMock()
        session.get.return_value = _response(200, {"dt": 1})

        assert _fetch_once(session, "https://example.com", structlog.get_logger()) == {"dt": 1}

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

            is_valid, _ = validate_credentials("test-key", "51.5,-0.12")

        assert is_valid is expected_valid

    def test_malformed_locations_is_invalid_without_request(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            is_valid, message = validate_credentials("test-key", "not-a-location")

        assert is_valid is False
        assert message is not None
        mock_session.return_value.get.assert_not_called()

    def test_network_error_is_invalid(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")

            is_valid, message = validate_credentials("test-key", "51.5,-0.12")

        assert is_valid is False
        assert message is not None

    def test_probes_current_weather_with_first_location(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200)

            validate_credentials("test-key", "51.5,-0.12,London\n40.7,-74.0")

            called_url = mock_session.return_value.get.call_args[0][0]

        assert called_url.startswith(f"{OPENWEATHER_BASE_URL}/data/2.5/weather?")
        assert "lat=51.5" in called_url


class TestGetRows:
    def test_yields_one_batch_per_location_and_targets_each(self):
        locations = [Location(51.5, -0.12, "London"), Location(40.7, -74.0, "New York")]
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [
                _response(200, {"dt": 1, "main": {"temp": 280}}),
                _response(200, {"dt": 2, "main": {"temp": 290}}),
            ]

            batches = list(get_rows("test-key", "current_weather", locations, structlog.get_logger()))

            called_urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]

        assert len(batches) == 2
        assert batches[0][0]["lat"] == 51.5
        assert batches[1][0]["lat"] == 40.7
        assert "lat=51.5" in called_urls[0]
        assert "lat=40.7" in called_urls[1]

    def test_skips_empty_responses(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200, {"list": []})

            batches = list(get_rows("test-key", "forecast", [Location(51.5, -0.12, None)], structlog.get_logger()))

        assert batches == []


class TestOpenWeatherSource:
    @pytest.mark.parametrize("endpoint", list(OPENWEATHER_ENDPOINTS))
    def test_source_response_shape(self, endpoint):
        response = openweather_source("test-key", endpoint, "51.5,-0.12,London", structlog.get_logger())

        assert response.name == endpoint
        assert response.primary_keys == ["lat", "lon", "dt"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["dt_iso"]
        assert response.sort_mode == "asc"

    def test_invalid_locations_raise(self):
        with pytest.raises(ValueError):
            openweather_source("test-key", "current_weather", "garbage", structlog.get_logger())
