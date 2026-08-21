import json
from typing import Any, Optional

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.breezometer.breezometer import (
    MAX_LOCATIONS,
    MAX_PAGES_PER_LOCATION,
    BreezometerRetryableError,
    Location,
    _build_request,
    _date_obj_to_iso,
    _datetime_str_to_iso,
    _fetch,
    _normalize_rows,
    _redact_key,
    breezometer_source,
    get_rows,
    parse_locations,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.breezometer.settings import BREEZOMETER_ENDPOINTS

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.breezometer.breezometer"

# Source the base URLs from the endpoint configs (the single source of truth) rather than duplicating
# the literals here, so a base-URL change in settings can't leave these assertions checking a stale value.
AIR_QUALITY_BASE_URL = BREEZOMETER_ENDPOINTS["air_quality_current"].base_url
POLLEN_BASE_URL = BREEZOMETER_ENDPOINTS["pollen_forecast"].base_url


def _response(status: int = 200, body: Optional[dict[str, Any]] = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = body or {}
    resp.text = json.dumps(body or {})
    if not resp.ok:
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"{status} Client Error for url: {AIR_QUALITY_BASE_URL}", response=requests.Response()
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
            ("40.7,-74.0,New York, NY", [Location(40.7, -74.0, "New York, NY")]),
        ],
    )
    def test_valid(self, raw, expected):
        assert parse_locations(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [None, "", "   \n  ", "51.5", "abc,def", "91,0", "0,181"],
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


class TestTimestampParsing:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ({"year": 2024, "month": 6, "day": 23}, "2024-06-23T00:00:00+00:00"),
            ({"year": 2024, "month": 1, "day": 1}, "2024-01-01T00:00:00+00:00"),
            (None, None),
            ({"year": 2024}, None),
            ("not-a-dict", None),
            ({"year": "x", "month": 1, "day": 1}, None),
        ],
    )
    def test_date_obj_to_iso(self, value, expected):
        assert _date_obj_to_iso(value) == expected

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("2023-08-11T08:00:00Z", "2023-08-11T08:00:00+00:00"),
            ("2023-08-11T08:00:00+00:00", "2023-08-11T08:00:00+00:00"),
            # A non-UTC offset is normalized back to UTC.
            ("2023-08-11T10:00:00+02:00", "2023-08-11T08:00:00+00:00"),
            (None, None),
            ("", None),
            ("garbage", None),
            (12345, None),
        ],
    )
    def test_datetime_str_to_iso(self, value, expected):
        assert _datetime_str_to_iso(value) == expected


class TestRedactKey:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("https://x/v1/a:lookup?key=secret", "https://x/v1/a:lookup?key=REDACTED"),
            ("https://x/v1/a:lookup?key=secret&days=5", "https://x/v1/a:lookup?key=REDACTED&days=5"),
            ("https://x/v1/a:lookup?days=5&key=secret", "https://x/v1/a:lookup?days=5&key=REDACTED"),
            # A field that merely contains "key" must not be redacted — only the `key` query param.
            ("https://x/v1/a:lookup?pageToken=abc", "https://x/v1/a:lookup?pageToken=abc"),
            ("no key here", "no key here"),
        ],
    )
    def test_redact(self, text, expected):
        assert _redact_key(text) == expected


class TestBuildRequest:
    def test_air_quality_current_is_post_with_body(self):
        url, body = _build_request(
            BREEZOMETER_ENDPOINTS["air_quality_current"], "secret-key", Location(51.5, -0.12), None
        )

        assert url == f"{AIR_QUALITY_BASE_URL}/v1/currentConditions:lookup?key=secret-key"
        assert body is not None
        assert body["location"] == {"latitude": 51.5, "longitude": -0.12}
        assert "extraComputations" in body
        # Current conditions take neither a forecast period nor a history window.
        assert "period" not in body and "hours" not in body

    def test_air_quality_forecast_includes_period(self):
        _, body = _build_request(
            BREEZOMETER_ENDPOINTS["air_quality_forecast"], "secret-key", Location(51.5, -0.12), None
        )

        assert body is not None
        assert set(body["period"]) == {"startTime", "endTime"}
        assert body["period"]["startTime"].endswith("Z")

    def test_air_quality_history_includes_hours(self):
        _, body = _build_request(
            BREEZOMETER_ENDPOINTS["air_quality_history"], "secret-key", Location(51.5, -0.12), None
        )

        assert body is not None
        assert body["hours"] == 24

    def test_air_quality_page_token_goes_in_body(self):
        _, body = _build_request(
            BREEZOMETER_ENDPOINTS["air_quality_forecast"], "secret-key", Location(51.5, -0.12), "next-page"
        )

        assert body is not None
        assert body["pageToken"] == "next-page"

    def test_pollen_is_get_with_query_params(self):
        url, body = _build_request(BREEZOMETER_ENDPOINTS["pollen_forecast"], "secret-key", Location(51.5, -0.12), None)

        assert body is None
        assert url.startswith(f"{POLLEN_BASE_URL}/v1/forecast:lookup?")
        assert "key=secret-key" in url
        assert "location.latitude=51.5" in url
        assert "location.longitude=-0.12" in url
        assert "days=5" in url

    def test_pollen_page_token_goes_in_query(self):
        url, _ = _build_request(
            BREEZOMETER_ENDPOINTS["pollen_forecast"], "secret-key", Location(51.5, -0.12), "next-page"
        )

        assert "pageToken=next-page" in url


class TestNormalizeRows:
    def test_current_conditions_single_row_with_injected_coords(self):
        response = {"dateTime": "2023-08-11T08:00:00Z", "regionCode": "uk", "indexes": [{"aqi": 42}]}
        rows = _normalize_rows(BREEZOMETER_ENDPOINTS["air_quality_current"], response, Location(51.5, -0.12, "London"))

        assert len(rows) == 1
        row = rows[0]
        assert row["latitude"] == 51.5
        assert row["longitude"] == -0.12
        assert row["location_label"] == "London"
        assert row["dt_iso"] == "2023-08-11T08:00:00+00:00"
        assert row["indexes"] == [{"aqi": 42}]

    def test_forecast_yields_one_row_per_hour(self):
        response = {
            "hourlyForecasts": [
                {"dateTime": "2023-08-11T08:00:00Z", "indexes": [{"aqi": 1}]},
                {"dateTime": "2023-08-11T09:00:00Z", "indexes": [{"aqi": 2}]},
            ]
        }
        rows = _normalize_rows(BREEZOMETER_ENDPOINTS["air_quality_forecast"], response, Location(51.5, -0.12))

        assert [row["dt_iso"] for row in rows] == ["2023-08-11T08:00:00+00:00", "2023-08-11T09:00:00+00:00"]
        assert all(row["latitude"] == 51.5 and row["longitude"] == -0.12 for row in rows)

    def test_pollen_builds_dt_iso_from_date_object(self):
        response = {"dailyInfo": [{"date": {"year": 2024, "month": 6, "day": 23}, "pollenTypeInfo": []}]}
        rows = _normalize_rows(BREEZOMETER_ENDPOINTS["pollen_forecast"], response, Location(51.5, -0.12))

        assert len(rows) == 1
        assert rows[0]["dt_iso"] == "2024-06-23T00:00:00+00:00"

    def test_rows_with_unparseable_timestamp_are_skipped(self):
        # dt_iso is part of the primary/partition key; a row whose timestamp is present but unparseable
        # must not flow a null key into the merge.
        response = {
            "hourlyForecasts": [{"dateTime": "", "indexes": [{"aqi": 1}]}, {"dateTime": "2023-08-11T08:00:00Z"}]
        }
        rows = _normalize_rows(BREEZOMETER_ENDPOINTS["air_quality_forecast"], response, Location(51.5, -0.12))

        assert len(rows) == 1
        assert rows[0]["dt_iso"] == "2023-08-11T08:00:00+00:00"

    def test_missing_timestamp_field_raises(self):
        # A missing timestamp field signals a structural API change (e.g. a renamed field) and must fail
        # loudly rather than silently dropping every row and reporting a successful zero-row sync.
        response = {"hourlyForecasts": [{"indexes": [{"aqi": 1}]}]}
        with pytest.raises(KeyError):
            _normalize_rows(BREEZOMETER_ENDPOINTS["air_quality_forecast"], response, Location(51.5, -0.12))


# tenacity exposes the undecorated function via `__wrapped__`, so status classification can be
# asserted without waiting through retry backoff.
_fetch_once = _fetch.__wrapped__  # type: ignore[attr-defined]


class TestFetch:
    def test_air_quality_uses_post(self):
        session = mock.MagicMock()
        session.post.return_value = _response(200, {"dateTime": "2023-08-11T08:00:00Z"})

        body = _fetch_once(
            session,
            BREEZOMETER_ENDPOINTS["air_quality_current"],
            "k",
            Location(51.5, -0.12),
            None,
            structlog.get_logger(),
        )

        assert body == {"dateTime": "2023-08-11T08:00:00Z"}
        session.post.assert_called_once()
        session.get.assert_not_called()

    def test_pollen_uses_get(self):
        session = mock.MagicMock()
        session.get.return_value = _response(200, {"dailyInfo": []})

        _fetch_once(
            session, BREEZOMETER_ENDPOINTS["pollen_forecast"], "k", Location(51.5, -0.12), None, structlog.get_logger()
        )

        session.get.assert_called_once()
        session.post.assert_not_called()

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable(self, status):
        session = mock.MagicMock()
        session.post.return_value = _response(status)

        with pytest.raises(BreezometerRetryableError):
            _fetch_once(
                session,
                BREEZOMETER_ENDPOINTS["air_quality_current"],
                "k",
                Location(51.5, -0.12),
                None,
                structlog.get_logger(),
            )

    def test_client_error_raises_for_status(self):
        session = mock.MagicMock()
        session.post.return_value = _response(400)

        with pytest.raises(requests.HTTPError):
            _fetch_once(
                session,
                BREEZOMETER_ENDPOINTS["air_quality_current"],
                "k",
                Location(51.5, -0.12),
                None,
                structlog.get_logger(),
            )

    def test_error_message_redacts_key(self):
        resp = mock.MagicMock()
        resp.status_code = 400
        resp.ok = False
        resp.text = '{"error":{"message":"API key not valid."}}'
        resp.raise_for_status.side_effect = requests.HTTPError(
            "400 Client Error: Bad Request for url: "
            "https://airquality.googleapis.com/v1/currentConditions:lookup?key=SUPERSECRETKEY",
            response=requests.Response(),
        )
        session = mock.MagicMock()
        session.post.return_value = resp

        with pytest.raises(requests.HTTPError) as exc_info:
            _fetch_once(
                session,
                BREEZOMETER_ENDPOINTS["air_quality_current"],
                "k",
                Location(51.5, -0.12),
                None,
                structlog.get_logger(),
            )

        message = str(exc_info.value)
        assert "SUPERSECRETKEY" not in message
        assert "key=REDACTED" in message
        # The host prefix is preserved so non-retryable-error matching still works.
        assert "for url: https://airquality.googleapis.com" in message


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid",
        [(200, True), (400, False), (403, False), (500, False)],
    )
    def test_status_mapping(self, status, expected_valid):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.post.return_value = _response(status)

            is_valid, _ = validate_credentials("test-key", "51.5,-0.12")

        assert is_valid is expected_valid

    def test_malformed_locations_is_invalid_without_request(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            is_valid, message = validate_credentials("test-key", "not-a-location")

        assert is_valid is False
        assert message is not None
        mock_session.return_value.post.assert_not_called()

    def test_network_error_is_invalid(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.post.side_effect = Exception("boom")

            is_valid, message = validate_credentials("test-key", "51.5,-0.12")

        assert is_valid is False
        assert message is not None

    def test_probes_current_conditions_with_first_location(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.post.return_value = _response(200)

            validate_credentials("test-key", "51.5,-0.12,London\n40.7,-74.0")

            called_url = mock_session.return_value.post.call_args[0][0]
            called_body = mock_session.return_value.post.call_args.kwargs["json"]

        assert called_url.startswith(f"{AIR_QUALITY_BASE_URL}/v1/currentConditions:lookup?")
        assert called_body["location"] == {"latitude": 51.5, "longitude": -0.12}


class TestGetRows:
    def test_yields_one_batch_per_location_and_targets_each(self):
        locations = [Location(51.5, -0.12, "London"), Location(40.7, -74.0, "New York")]
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.post.side_effect = [
                _response(200, {"dateTime": "2023-08-11T08:00:00Z", "indexes": []}),
                _response(200, {"dateTime": "2023-08-11T09:00:00Z", "indexes": []}),
            ]

            batches = list(get_rows("test-key", "air_quality_current", locations, structlog.get_logger()))

        assert len(batches) == 2
        assert batches[0][0]["latitude"] == 51.5
        assert batches[1][0]["latitude"] == 40.7

    def test_follows_next_page_token(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.post.side_effect = [
                _response(200, {"hourlyForecasts": [{"dateTime": "2023-08-11T08:00:00Z"}], "nextPageToken": "p2"}),
                _response(200, {"hourlyForecasts": [{"dateTime": "2023-08-11T09:00:00Z"}]}),
            ]

            batches = list(
                get_rows("test-key", "air_quality_forecast", [Location(51.5, -0.12)], structlog.get_logger())
            )

            # The second request must carry the page token from the first response.
            second_body = mock_session.return_value.post.call_args_list[1].kwargs["json"]

        assert len(batches) == 2
        assert second_body["pageToken"] == "p2"

    def test_page_cap_stops_unbounded_pagination(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            # Every response advertises another page; the cap must stop the loop.
            mock_session.return_value.post.return_value = _response(
                200, {"hourlyForecasts": [{"dateTime": "2023-08-11T08:00:00Z"}], "nextPageToken": "loop"}
            )

            batches = list(
                get_rows("test-key", "air_quality_forecast", [Location(51.5, -0.12)], structlog.get_logger())
            )

        assert len(batches) == MAX_PAGES_PER_LOCATION

    def test_skips_empty_responses(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200, {"dailyInfo": []})

            batches = list(get_rows("test-key", "pollen_forecast", [Location(51.5, -0.12)], structlog.get_logger()))

        assert batches == []


class TestBreezometerSource:
    @pytest.mark.parametrize("endpoint", list(BREEZOMETER_ENDPOINTS))
    def test_source_response_shape(self, endpoint):
        response = breezometer_source("test-key", endpoint, "51.5,-0.12,London", structlog.get_logger())

        assert response.name == endpoint
        assert response.primary_keys == ["latitude", "longitude", "dt_iso"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["dt_iso"]
        assert response.sort_mode == "asc"

    def test_invalid_locations_raise(self):
        with pytest.raises(ValueError):
            breezometer_source("test-key", "air_quality_current", "garbage", structlog.get_logger())
