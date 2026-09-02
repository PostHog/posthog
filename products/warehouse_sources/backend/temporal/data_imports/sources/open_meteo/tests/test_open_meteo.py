import json
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.open_meteo.open_meteo import (
    ARCHIVE_WINDOW_DAYS,
    DEFAULT_ARCHIVE_BACKFILL_DAYS,
    MAX_LABEL_LENGTH,
    MAX_LOCATIONS,
    Location,
    OpenMeteoResumeConfig,
    _fetch,
    _redact_apikey,
    base_url,
    build_params,
    get_rows,
    normalize_rows,
    open_meteo_source,
    parse_locations,
    parse_start_date,
    parse_time,
    resolve_archive_range,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.open_meteo.settings import OPEN_METEO_ENDPOINTS

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.open_meteo.open_meteo"

LONDON = Location(51.5074, -0.1278, "London")
NEW_YORK = Location(40.7128, -74.006)


class FakeResumeManager(ResumableSourceManager[OpenMeteoResumeConfig]):
    def __init__(self, state: OpenMeteoResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[OpenMeteoResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> OpenMeteoResumeConfig | None:
        return self.state

    def save_state(self, data: OpenMeteoResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True


def _response(status: int = 200, body: dict[str, Any] | None = None) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status
    response.ok = 200 <= status < 300
    response.reason = "Bad Request" if status == 400 else "Unauthorized" if status == 401 else "OK"
    response.json.return_value = body if body is not None else {}
    response.text = json.dumps(body or {})
    response.raise_for_status.side_effect = (
        None
        if response.ok
        else requests.HTTPError(
            f"{status} Server Error for url: https://api.open-meteo.com/v1/forecast?apikey=secret",
            response=requests.Response(),
        )
    )
    return response


def _hourly_body(times: list[str], **series: list[Any]) -> dict[str, Any]:
    return {
        "latitude": 51.5,
        "longitude": -0.125,
        "elevation": 23.0,
        "timezone": "GMT",
        "utc_offset_seconds": 0,
        "hourly": {"time": times, **series},
    }


def _fake_session(responses: list[mock.MagicMock]) -> mock.MagicMock:
    session = mock.MagicMock()
    session.get.side_effect = responses
    return session


def _requested_urls(session: mock.MagicMock) -> list[str]:
    return [call.args[0] for call in session.get.call_args_list]


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


class TestParseLocations:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("51.5,-0.12", [Location(51.5, -0.12, None)]),
            ("51.5,-0.12,London", [Location(51.5, -0.12, "London")]),
            ("  51.5 , -0.12 , London  ", [Location(51.5, -0.12, "London")]),
            ("51.5,-0.12\n\n  \n40.7,-74.0", [Location(51.5, -0.12), Location(40.7, -74.0)]),
            ("40.7,-74.0,New York, NY", [Location(40.7, -74.0, "New York, NY")]),
        ],
    )
    def test_valid(self, raw: str, expected: list[Location]) -> None:
        assert parse_locations(raw) == expected

    @pytest.mark.parametrize(
        "raw,message",
        [
            (None, "At least one location"),
            ("", "At least one location"),
            ("   \n  ", "At least one location"),
            ("51.5", "must be in the form"),
            ("abc,def", "non-numeric"),
            ("91,0", "out of range"),
            ("0,181", "out of range"),
            # Two identical coordinates would share a `location_id` and merge into a single row.
            ("51.5,-0.12,London\n51.5,-0.12,Londres", "repeats a location"),
        ],
    )
    def test_invalid_raises(self, raw: str | None, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            parse_locations(raw)

    def test_rejects_more_than_max_locations(self) -> None:
        raw = "\n".join(f"{index}.5,0" for index in range(MAX_LOCATIONS + 1))
        with pytest.raises(ValueError, match="Too many locations"):
            parse_locations(raw)

    def test_allows_exactly_max_locations(self) -> None:
        raw = "\n".join(f"{index}.5,0" for index in range(MAX_LOCATIONS))
        assert len(parse_locations(raw)) == MAX_LOCATIONS

    def test_rejects_an_oversized_label(self) -> None:
        # The label is copied onto every row of every batch, so an unbounded one is amplified by the
        # batch's row count and can exhaust the worker.
        with pytest.raises(ValueError, match="label of"):
            parse_locations(f"51.5,-0.12,{'x' * (MAX_LABEL_LENGTH + 1)}")

    def test_allows_a_label_of_exactly_the_maximum_length(self) -> None:
        label = "x" * MAX_LABEL_LENGTH
        assert parse_locations(f"51.5,-0.12,{label}") == [Location(51.5, -0.12, label)]


class TestParseStartDate:
    @pytest.mark.parametrize("raw,expected", [(None, None), ("", None), ("  ", None), ("2024-01-01", date(2024, 1, 1))])
    def test_valid(self, raw: str | None, expected: date | None) -> None:
        assert parse_start_date(raw) == expected

    @pytest.mark.parametrize("raw", ["01/01/2024", "2024-13-01", "yesterday"])
    def test_invalid_raises(self, raw: str) -> None:
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            parse_start_date(raw)


class TestParseTime:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2026-01-02T03:00", datetime(2026, 1, 2, 3, 0, tzinfo=UTC)),
            ("2026-01-02", datetime(2026, 1, 2, 0, 0, tzinfo=UTC)),
        ],
    )
    def test_returns_utc_aware_datetime(self, raw: str, expected: datetime) -> None:
        parsed = parse_time(raw)
        assert parsed == expected
        # A naive datetime would be incomparable with the stored watermark.
        assert parsed.tzinfo is not None


class TestRequestBuilding:
    @pytest.mark.parametrize(
        "endpoint_name,api_key,expected_host",
        [
            ("weather_forecast_hourly", None, "https://api.open-meteo.com"),
            ("weather_forecast_hourly", "key", "https://customer-api.open-meteo.com"),
            ("weather_archive_hourly", None, "https://archive-api.open-meteo.com"),
            ("weather_archive_hourly", "key", "https://customer-archive-api.open-meteo.com"),
            ("air_quality_hourly", None, "https://air-quality-api.open-meteo.com"),
            ("air_quality_hourly", "key", "https://customer-air-quality-api.open-meteo.com"),
        ],
    )
    def test_commercial_host_only_used_with_an_api_key(
        self, endpoint_name: str, api_key: str | None, expected_host: str
    ) -> None:
        assert base_url(OPEN_METEO_ENDPOINTS[endpoint_name], api_key) == expected_host

    def test_params_carry_the_endpoint_block_and_variables(self) -> None:
        endpoint = OPEN_METEO_ENDPOINTS["weather_archive_daily"]
        params = build_params(endpoint, LONDON, None, start=date(2026, 1, 1), end=date(2026, 1, 31))

        assert params["latitude"] == LONDON.latitude
        assert params["longitude"] == LONDON.longitude
        assert params["daily"] == ",".join(endpoint.variables)
        assert "hourly" not in params
        assert params["timezone"] == "GMT"
        assert params["start_date"] == "2026-01-01"
        assert params["end_date"] == "2026-01-31"
        assert "apikey" not in params

    def test_rolling_params_have_no_date_window_and_carry_the_key(self) -> None:
        params = build_params(OPEN_METEO_ENDPOINTS["air_quality_hourly"], LONDON, "secret")

        assert "start_date" not in params
        assert "end_date" not in params
        assert params["past_days"] == 7
        assert params["forecast_days"] == 5
        assert params["apikey"] == "secret"

    def test_redacts_the_api_key(self) -> None:
        assert _redact_apikey("...?latitude=1&apikey=secret&hourly=x") == "...?latitude=1&apikey=REDACTED&hourly=x"


class TestNormalizeRows:
    def test_pivots_parallel_arrays_into_one_row_per_timestamp(self) -> None:
        payload = _hourly_body(
            ["2026-01-01T00:00", "2026-01-01T01:00"],
            temperature_2m=[1.5, 2.5],
            wind_speed_10m=[10.0, 11.0],
        )

        rows = normalize_rows(OPEN_METEO_ENDPOINTS["weather_archive_hourly"], payload, LONDON)

        assert [row["time"] for row in rows] == ["2026-01-01T00:00", "2026-01-01T01:00"]
        assert [row["temperature_2m"] for row in rows] == [1.5, 2.5]
        assert [row["wind_speed_10m"] for row in rows] == [10.0, 11.0]
        assert [row["time_utc"] for row in rows] == [
            datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
        ]

    def test_stamps_requested_coordinates_and_keeps_the_served_grid_cell_separate(self) -> None:
        payload = _hourly_body(["2026-01-01T00:00"], temperature_2m=[1.5])

        row = normalize_rows(OPEN_METEO_ENDPOINTS["weather_archive_hourly"], payload, LONDON)[0]

        # The primary key is built from the configured coordinates, so they must survive verbatim
        # rather than being overwritten by the grid cell Open-Meteo snapped to.
        assert row["location_id"] == "51.5074,-0.1278"
        assert row["latitude"] == 51.5074
        assert row["longitude"] == -0.1278
        assert row["location_label"] == "London"
        assert row["resolved_latitude"] == 51.5
        assert row["resolved_longitude"] == -0.125
        assert row["elevation"] == 23.0

    def test_pads_a_short_series_rather_than_shifting_later_values(self) -> None:
        payload = _hourly_body(
            ["2026-01-01T00:00", "2026-01-01T01:00", "2026-01-01T02:00"],
            temperature_2m=[1.5, 2.5],
        )

        rows = normalize_rows(OPEN_METEO_ENDPOINTS["weather_archive_hourly"], payload, LONDON)

        assert [row["temperature_2m"] for row in rows] == [1.5, 2.5, None]

    def test_current_block_yields_a_single_flat_row(self) -> None:
        payload = {
            "latitude": 51.5,
            "longitude": -0.125,
            "current": {"time": "2026-01-01T00:15", "interval": 900, "temperature_2m": 4.2},
        }

        rows = normalize_rows(OPEN_METEO_ENDPOINTS["weather_current"], payload, LONDON)

        assert len(rows) == 1
        assert rows[0]["temperature_2m"] == 4.2
        assert rows[0]["interval"] == 900
        assert rows[0]["time_utc"] == datetime(2026, 1, 1, 0, 15, tzinfo=UTC)

    @pytest.mark.parametrize("payload", [{}, {"hourly": None}, {"hourly": {"time": None}}])
    def test_missing_block_yields_no_rows(self, payload: dict[str, Any]) -> None:
        assert normalize_rows(OPEN_METEO_ENDPOINTS["weather_archive_hourly"], payload, LONDON) == []

    @pytest.mark.parametrize("payload", [{}, {"current": None}, {"current": {"temperature_2m": 4.2}}])
    def test_current_block_without_a_timestamp_yields_no_rows(self, payload: dict[str, Any]) -> None:
        # `time_utc` is the partition key, so a row without one is unusable. Dropping it matches the
        # hourly/daily path rather than raising a `KeyError` out of the middle of a sync.
        assert normalize_rows(OPEN_METEO_ENDPOINTS["weather_current"], payload, LONDON) == []


class TestFetch:
    def test_maps_401_to_the_permanent_api_key_error(self) -> None:
        session = _fake_session([_response(401, {"error": True, "reason": "Invalid API key"})])

        with pytest.raises(requests.HTTPError, match="Open-Meteo rejected the API key"):
            _fetch(session, "https://customer-api.open-meteo.com/v1/forecast")

    @pytest.mark.parametrize("status", [400, 404])
    def test_maps_other_4xx_to_the_permanent_request_error_with_the_reason(self, status: int) -> None:
        session = _fake_session(
            [_response(status, {"error": True, "reason": "Latitude must be in range of -90 to 90"})]
        )

        with pytest.raises(requests.HTTPError, match="Latitude must be in range"):
            _fetch(session, "https://archive-api.open-meteo.com/v1/archive")

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_transient_statuses_are_not_reported_as_permanent_rejections(self, status: int) -> None:
        # The tracked session's adapter already retried these; surfacing them under the
        # `get_non_retryable_errors` wording would permanently disable the source instead.
        session = _fake_session([_response(status, {})])

        with pytest.raises(requests.HTTPError) as excinfo:
            _fetch(session, "https://api.open-meteo.com/v1/forecast")

        assert "Open-Meteo rejected" not in str(excinfo.value)
        assert "apikey=REDACTED" in str(excinfo.value)

    def test_falls_back_to_the_http_reason_when_the_error_body_is_not_json(self) -> None:
        response = _response(400, {})
        response.json.side_effect = ValueError("no json here")
        session = _fake_session([response])

        with pytest.raises(requests.HTTPError, match="Bad Request"):
            _fetch(session, "https://archive-api.open-meteo.com/v1/archive")

    @pytest.mark.parametrize(
        "error",
        [
            requests.ConnectionError(
                "HTTPSConnectionPool(host='customer-api.open-meteo.com', port=443): Max retries exceeded "
                "with url: /v1/forecast?latitude=51.5&apikey=super-secret&hourly=temperature_2m"
            ),
            requests.Timeout("Read timed out for url: /v1/forecast?apikey=super-secret"),
            requests.exceptions.RetryError("too many retries: /v1/archive?apikey=super-secret&start_date=2024-01-01"),
        ],
    )
    def test_transport_errors_never_carry_the_api_key(self, error: Exception) -> None:
        # These propagate out of the sync into `ExternalDataJob.latest_error` and the logs, so the
        # commercial key must not survive in the message. The exception type is kept intact so
        # callers classify the failure exactly as they did before.
        session = mock.MagicMock()
        session.get.side_effect = error

        with pytest.raises(requests.RequestException) as excinfo:
            _fetch(session, "https://customer-api.open-meteo.com/v1/forecast?apikey=super-secret")

        assert isinstance(excinfo.value, type(error))
        assert "super-secret" not in str(excinfo.value)
        assert "apikey=REDACTED" in str(excinfo.value)
        # The original, unredacted exception must not ride along as the chained cause either.
        assert excinfo.value.__cause__ is None
        assert excinfo.value.__context__ is None or excinfo.value.__suppress_context__

    def test_a_subclass_that_cannot_be_rebuilt_still_has_the_key_stripped(self) -> None:
        # Some `RequestException` subclasses take a stricter signature than a single message
        # (`JSONDecodeError`, for one). Losing the exact class is acceptable; leaking the key is not.
        class StrictError(requests.RequestException):
            def __init__(self, message: str, code: int) -> None:
                super().__init__(message)
                self.code = code

        session = mock.MagicMock()
        session.get.side_effect = StrictError("failed for url: /v1/forecast?apikey=super-secret", 7)

        with pytest.raises(requests.RequestException) as excinfo:
            _fetch(session, "https://customer-api.open-meteo.com/v1/forecast?apikey=super-secret")

        assert "super-secret" not in str(excinfo.value)
        assert "apikey=REDACTED" in str(excinfo.value)


class TestResolveArchiveRange:
    TODAY = date(2026, 6, 1)

    def test_falls_back_to_a_bounded_backfill_when_nothing_is_configured(self) -> None:
        start, end = resolve_archive_range(None, None, self.TODAY)

        assert end == self.TODAY
        assert (self.TODAY - start).days == DEFAULT_ARCHIVE_BACKFILL_DAYS

    def test_uses_the_configured_start_date(self) -> None:
        assert resolve_archive_range(date(2020, 1, 1), None, self.TODAY) == (date(2020, 1, 1), self.TODAY)

    @pytest.mark.parametrize(
        "watermark",
        [datetime(2026, 5, 20, 6, 0, tzinfo=UTC), date(2026, 5, 20), "2026-05-20T06:00"],
    )
    def test_watermark_wins_over_the_configured_start(self, watermark: Any) -> None:
        start, end = resolve_archive_range(date(2020, 1, 1), watermark, self.TODAY)

        assert start == date(2026, 5, 20)
        assert end == self.TODAY

    def test_returns_an_empty_range_once_the_watermark_reaches_today(self) -> None:
        start, end = resolve_archive_range(None, datetime(2026, 6, 2, tzinfo=UTC), self.TODAY)

        assert start > end


class TestArchiveWindowing:
    def _run(
        self, manager: FakeResumeManager, responses: list[mock.MagicMock], start: str
    ) -> tuple[list[list[dict[str, Any]]], mock.MagicMock]:
        session = _fake_session(responses)
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            batches = list(
                get_rows(
                    endpoint_name="weather_archive_hourly",
                    locations=[LONDON, NEW_YORK],
                    api_key=None,
                    configured_start=date.fromisoformat(start),
                    db_incremental_field_last_value=None,
                    resumable_source_manager=manager,
                    logger=structlog.get_logger(),
                )
            )
        return batches, session

    @freeze_time("2026-03-01")
    def test_covers_every_location_within_a_window_before_advancing(self) -> None:
        manager = FakeResumeManager()
        responses = [_response(200, _hourly_body(["2026-01-01T00:00"], temperature_2m=[1.0])) for _ in range(4)]

        batches, session = self._run(manager, responses, "2026-01-01")

        windows = [(_query(url)["start_date"][0], _query(url)["end_date"][0]) for url in _requested_urls(session)]
        latitudes = [_query(url)["latitude"][0] for url in _requested_urls(session)]

        # Windows outermost, locations innermost. Locations outermost would let the pipeline
        # checkpoint the watermark at London's newest row while New York still had history to fetch.
        assert windows == [
            ("2026-01-01", "2026-01-31"),
            ("2026-01-01", "2026-01-31"),
            ("2026-02-01", "2026-03-01"),
            ("2026-02-01", "2026-03-01"),
        ]
        assert latitudes == ["51.5074", "40.7128", "51.5074", "40.7128"]
        # One batch per window, holding both locations' rows.
        assert [len(batch) for batch in batches] == [2, 2]

    @freeze_time("2026-03-01")
    def test_windows_are_contiguous_and_never_overlap(self) -> None:
        manager = FakeResumeManager()
        responses = [_response(200, _hourly_body(["2026-01-01T00:00"], temperature_2m=[1.0])) for _ in range(4)]

        _, session = self._run(manager, responses, "2026-01-01")

        boundaries = [
            (date.fromisoformat(_query(url)["start_date"][0]), date.fromisoformat(_query(url)["end_date"][0]))
            for url in _requested_urls(session)
        ]
        first, second = boundaries[0], boundaries[2]
        assert (first[1] - first[0]).days == ARCHIVE_WINDOW_DAYS - 1
        assert (second[0] - first[1]).days == 1

    @freeze_time("2026-03-01")
    def test_checkpoints_after_each_window_and_clears_on_completion(self) -> None:
        manager = FakeResumeManager()
        responses = [_response(200, _hourly_body(["2026-01-01T00:00"], temperature_2m=[1.0])) for _ in range(4)]

        self._run(manager, responses, "2026-01-01")

        assert [state.next_start_date for state in manager.saved] == ["2026-02-01", "2026-03-02"]
        assert manager.cleared is True

    @freeze_time("2026-03-01")
    def test_resumes_from_the_saved_window(self) -> None:
        manager = FakeResumeManager(OpenMeteoResumeConfig(next_start_date="2026-02-01"))
        responses = [_response(200, _hourly_body(["2026-02-01T00:00"], temperature_2m=[1.0])) for _ in range(2)]

        _, session = self._run(manager, responses, "2026-01-01")

        assert [_query(url)["start_date"][0] for url in _requested_urls(session)] == ["2026-02-01", "2026-02-01"]

    @freeze_time("2026-03-01")
    def test_makes_no_requests_when_the_watermark_is_already_current(self) -> None:
        manager = FakeResumeManager()
        session = _fake_session([])

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            batches = list(
                get_rows(
                    endpoint_name="weather_archive_hourly",
                    locations=[LONDON],
                    api_key=None,
                    configured_start=None,
                    db_incremental_field_last_value=datetime(2026, 3, 5, tzinfo=UTC),
                    resumable_source_manager=manager,
                    logger=structlog.get_logger(),
                )
            )

        assert batches == []
        assert session.get.call_count == 0


class TestRollingEndpoints:
    def _run(
        self, manager: FakeResumeManager, responses: list[mock.MagicMock], locations: list[Location]
    ) -> tuple[list[list[dict[str, Any]]], mock.MagicMock]:
        session = _fake_session(responses)
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            batches = list(
                get_rows(
                    endpoint_name="weather_forecast_hourly",
                    locations=locations,
                    api_key=None,
                    configured_start=None,
                    db_incremental_field_last_value=None,
                    resumable_source_manager=manager,
                    logger=structlog.get_logger(),
                )
            )
        return batches, session

    def test_one_request_and_batch_per_location_with_no_date_window(self) -> None:
        manager = FakeResumeManager()
        responses = [_response(200, _hourly_body(["2026-01-01T00:00"], temperature_2m=[1.0])) for _ in range(2)]

        batches, session = self._run(manager, responses, [LONDON, NEW_YORK])

        assert len(batches) == 2
        assert all("start_date" not in _query(url) for url in _requested_urls(session))
        assert [state.location_index for state in manager.saved] == [1, 2]
        assert manager.cleared is True

    def test_resumes_from_the_saved_location_index(self) -> None:
        manager = FakeResumeManager(OpenMeteoResumeConfig(location_index=1))
        responses = [_response(200, _hourly_body(["2026-01-01T00:00"], temperature_2m=[1.0]))]

        _, session = self._run(manager, responses, [LONDON, NEW_YORK])

        assert [_query(url)["latitude"][0] for url in _requested_urls(session)] == ["40.7128"]


class TestOpenMeteoSourceResponse:
    @pytest.mark.parametrize("endpoint_name", sorted(OPEN_METEO_ENDPOINTS))
    def test_response_metadata_matches_the_endpoint_catalog(self, endpoint_name: str) -> None:
        response = open_meteo_source(
            endpoint_name=endpoint_name,
            locations_raw="51.5,-0.12",
            api_key=None,
            start_date_raw=None,
            db_incremental_field_last_value=None,
            resumable_source_manager=FakeResumeManager(),
            logger=structlog.get_logger(),
        )

        endpoint = OPEN_METEO_ENDPOINTS[endpoint_name]
        assert response.name == endpoint_name
        assert response.primary_keys == endpoint.primary_keys
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["time_utc"]
        assert response.partition_format == endpoint.partition_format
        assert response.sort_mode == "asc"

    def test_bad_locations_fail_before_any_request_is_made(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            open_meteo_source(
                endpoint_name="weather_current",
                locations_raw="91,0",
                api_key=None,
                start_date_raw=None,
                db_incremental_field_last_value=None,
                resumable_source_manager=FakeResumeManager(),
                logger=structlog.get_logger(),
            )


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "locations,start_date,message",
        [
            ("", None, "At least one location"),
            ("91,0", None, "out of range"),
            ("51.5,-0.12", "01/01/2024", "YYYY-MM-DD"),
        ],
    )
    def test_rejects_bad_config_without_calling_the_api(
        self, locations: str, start_date: str | None, message: str
    ) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            ok, error = validate_credentials(locations, None, start_date)

        assert ok is False
        assert error is not None and message in error
        assert make_session.call_count == 0

    @pytest.mark.parametrize(
        "status,body,expected_ok,expected_message",
        [
            (200, {}, True, None),
            (401, {"reason": "Invalid API key"}, False, "rejected the API key"),
            (400, {"reason": "Latitude must be in range of -90 to 90"}, False, "Latitude must be in range"),
            (500, {}, False, "status 500"),
        ],
    )
    def test_maps_status_codes(
        self, status: int, body: dict[str, Any], expected_ok: bool, expected_message: str | None
    ) -> None:
        session = _fake_session([_response(status, body)])

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            ok, error = validate_credentials("51.5,-0.12", None, None)

        assert ok is expected_ok
        if expected_message is None:
            assert error is None
        else:
            assert error is not None and expected_message in error

    def test_non_json_error_body_still_reports_the_status(self) -> None:
        response = _response(500, {})
        response.json.side_effect = ValueError("not json")
        session = _fake_session([response])

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            ok, error = validate_credentials("51.5,-0.12", None, None)

        assert ok is False
        assert error == "Open-Meteo returned status 500"

    def test_unreachable_api_is_reported_as_a_retryable_message(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            ok, error = validate_credentials("51.5,-0.12", None, None)

        assert ok is False
        assert error == "Could not reach the Open-Meteo API. Please try again."
