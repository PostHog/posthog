from datetime import UTC, date, datetime
from typing import Literal

import pytest
import time_machine
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.meteostat import (
    MeteostatSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.meteostat import (
    INVALID_LOCATIONS_ERROR,
    NO_LOCATIONS_ERROR,
    NO_STATIONS_ERROR,
    MeteostatLocation,
    MeteostatResumeConfig,
    _coerce_date,
    _parse_station_ids,
    _parse_timestamp,
    parse_locations,
    start_date_error,
    validate_station,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.settings import (
    DAILY_ENDPOINT,
    HOURLY_ENDPOINT,
    MAX_LOCATIONS,
    MAX_STATIONS,
    METEOSTAT_ENDPOINTS,
    MINIMUM_START_DATE,
    MONTHLY_ENDPOINT,
    NORMALS_ENDPOINT,
    POINT_DAILY_ENDPOINT,
    POINT_NORMALS_ENDPOINT,
    STATIONS_ENDPOINT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.source import MeteostatSource


def _driver(
    station_ids: str = "10637",
    units: Literal["metric", "imperial", "scientific"] = "metric",
    start_date: str | None = None,
    locations: str | None = None,
) -> SourceDriver:
    return SourceDriver(
        MeteostatSource(),
        MeteostatSourceConfig(
            api_key="key-123", station_ids=station_ids, units=units, start_date=start_date, locations=locations
        ),
    )


class TestHelpers:
    @parameterized.expand(
        [
            ("none", None, []),
            ("empty", "", []),
            ("single", "10637", ["10637"]),
            ("commas_and_spaces", "10637, 71508 ,D1234", ["10637", "71508", "D1234"]),
            ("dedupes_repeats", "10637,10637,71508", ["10637", "71508"]),
        ]
    )
    def test_parse_station_ids(self, _name, value, expected):
        assert _parse_station_ids(value) == expected

    @parameterized.expand(
        [
            ("datetime", datetime(2026, 7, 1, 5, tzinfo=UTC), date(2026, 7, 1)),
            ("date", date(2026, 7, 1), date(2026, 7, 1)),
            ("iso", "2026-07-01", date(2026, 7, 1)),
            ("garbage", "not-a-date", None),
            ("none", None, None),
        ]
    )
    def test_coerce_date(self, _name, value, expected):
        assert _coerce_date(value) == expected

    @parameterized.expand(
        [
            ("too_old", "0001-01-01", False),
            ("exactly_at_floor", MINIMUM_START_DATE.isoformat(), True),
            ("comfortably_after_floor", "2015-01-01", True),
            ("none", None, True),
            ("unparsable_left_to_other_validation", "not-a-date", True),
        ]
    )
    def test_start_date_error(self, _name, value, expect_none):
        error = start_date_error(value)
        if expect_none:
            assert error is None
        else:
            assert error is not None and MINIMUM_START_DATE.isoformat() in error

    @parameterized.expand(
        [
            ("hourly", "2019-12-31 23:00:00", datetime(2019, 12, 31, 23, 0, 0)),
            ("daily", "2020-02-01", datetime(2020, 2, 1)),
            ("unparsable", "not-a-timestamp", "not-a-timestamp"),
            ("non_string", 42, 42),
            ("none", None, None),
        ]
    )
    def test_parse_timestamp(self, _name, value, expected):
        assert _parse_timestamp(value) == expected

    @parameterized.expand(
        [
            ("none", None, []),
            ("empty", "", []),
            ("pair", "43.6667,-79.4", [MeteostatLocation(43.6667, -79.4)]),
            ("triple_with_spaces", " 43.6667 , -79.4 , 113 ", [MeteostatLocation(43.6667, -79.4, 113)]),
            (
                "semicolons_new_lines_and_blank_entries",
                "1,2; 3,4\n\n5,6,7;",
                [MeteostatLocation(1, 2), MeteostatLocation(3, 4), MeteostatLocation(5, 6, 7)],
            ),
            ("dedupes_on_coordinates", "1,2,10;1,2,20", [MeteostatLocation(1, 2, 10)]),
            ("range_boundaries", "-90,-180;90,180", [MeteostatLocation(-90, -180), MeteostatLocation(90, 180)]),
            ("rounds_elevation", "1,2,113.6", [MeteostatLocation(1, 2, 114)]),
            ("empty_elevation", "1,2,", [MeteostatLocation(1, 2)]),
            (
                "duplicates_do_not_count_toward_the_cap",
                ";".join(f"{i},{i}" for i in range(MAX_LOCATIONS)) + ";0,0",
                [MeteostatLocation(i, i) for i in range(MAX_LOCATIONS)],
            ),
        ]
    )
    def test_parse_locations(self, _name, value, expected):
        assert parse_locations(value) == expected

    @parameterized.expand(
        [
            ("one_value", "43.6"),
            ("four_values", "1,2,3,4"),
            ("not_a_number", "north,west"),
            ("latitude_out_of_range", "91,0"),
            ("longitude_out_of_range", "0,-181"),
            ("nan_latitude", "nan,0"),
            ("infinite_elevation", "1,2,inf"),
            ("one_bad_entry_among_good_ones", "1,2;oops;3,4"),
            ("too_many", ";".join(f"{i},{i}" for i in range(MAX_LOCATIONS + 1))),
        ]
    )
    def test_parse_locations_rejects(self, _name, value):
        with pytest.raises(ValueError, match=INVALID_LOCATIONS_ERROR):
            parse_locations(value)


class TestGetRows:
    @time_machine.travel("2026-07-21", tick=False)
    def test_multiple_stations_are_each_queried_across_the_full_range(self):
        result = _driver(station_ids="10637, 71508", start_date="2026-07-18").run(
            DAILY_ENDPOINT,
            [ScriptedResponse(json={"data": [{"date": "2026-07-18", "tavg": 5.0}]})] * 2,
        )

        assert result.raised is None
        assert result.params("station") == ["10637", "71508"]
        assert [batch[0]["station_id"] for batch in result.items] == ["10637", "71508"]
        assert [row["date"] for row in result.rows] == [datetime(2026, 7, 18)] * 2

    @time_machine.travel("2026-07-21", tick=False)
    def test_incremental_start_uses_overlap_window(self):
        result = _driver().run(
            DAILY_ENDPOINT,
            [ScriptedResponse(json={"data": []})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 7, 15, tzinfo=UTC),
        )

        # Re-fetches a 7 day trailing overlap so late corrections get picked up; merge dedupes.
        assert result.raised is None
        assert result.params("station") == ["10637"]
        assert result.params("start") == ["2026-07-08"]
        assert result.params("end") == ["2026-07-21"]

    @time_machine.travel("2026-07-21", tick=False)
    def test_resume_state_skips_completed_stations_and_resumes_the_current_one(self):
        result = _driver(station_ids="10637,71508", start_date="2026-01-01").run(
            DAILY_ENDPOINT,
            [ScriptedResponse(json={"data": []})],
            resume_state=MeteostatResumeConfig(station_index=1, next_start="2026-07-19"),
        )

        # Station 0 already finished in a prior attempt; only station 1 is queried, resuming
        # from its saved cursor rather than restarting at start_date.
        assert result.raised is None
        assert result.params("station") == ["71508"]
        assert result.params("start") == ["2026-07-19"]
        assert result.params("end") == ["2026-07-21"]

    @parameterized.expand(
        [
            ("station_window", DAILY_ENDPOINT, NO_STATIONS_ERROR),
            ("station_snapshot", STATIONS_ENDPOINT, NO_STATIONS_ERROR),
            ("point_window", POINT_DAILY_ENDPOINT, NO_LOCATIONS_ERROR),
            ("point_snapshot", POINT_NORMALS_ENDPOINT, NO_LOCATIONS_ERROR),
        ]
    )
    def test_raises_without_configured_targets(self, _name, endpoint_name, error):
        result = _driver(station_ids="  ,  ", locations=" ; ").run(endpoint_name, [])

        assert isinstance(result.raised, ValueError)
        assert error in str(result.raised)
        assert result.requests == []

    @time_machine.travel("2026-07-21", tick=False)
    def test_point_tables_query_each_location_by_coordinates(self):
        result = _driver(locations="43.6667,-79.4,113; 59.9127,10.7461", start_date="2026-07-18").run(
            POINT_DAILY_ENDPOINT,
            [ScriptedResponse(json={"data": [{"date": "2026-07-18", "tavg": 5.0}]})] * 2,
        )

        assert result.raised is None
        assert set(result.paths) == {"/point/daily"}
        assert result.params("lat") == ["43.6667", "59.9127"]
        assert result.params("lon") == ["-79.4", "10.7461"]
        assert result.params("alt") == ["113", None]
        assert result.params("station") == [None, None]
        assert result.params("start") == ["2026-07-18"] * 2
        assert result.rows == [
            {"date": datetime(2026, 7, 18), "tavg": 5.0, "latitude": 43.6667, "longitude": -79.4, "altitude": 113},
            {"date": datetime(2026, 7, 18), "tavg": 5.0, "latitude": 59.9127, "longitude": 10.7461, "altitude": None},
        ]

    @time_machine.travel("2026-07-21", tick=False)
    def test_station_count_is_capped_at_runtime(self):
        station_ids = ",".join(str(i) for i in range(MAX_STATIONS + 5))
        logger = mock.MagicMock()
        result = _driver(station_ids=station_ids, start_date="2026-07-20").run(
            DAILY_ENDPOINT,
            [ScriptedResponse(json={"data": []})] * MAX_STATIONS,
            logger=logger,
        )

        assert result.raised is None
        assert result.params("station") == [str(i) for i in range(MAX_STATIONS)]
        logger.warning.assert_called_once()

    @parameterized.expand(
        [
            ("metric_omits_units_param", "metric", False),
            ("imperial_includes_units_param", "imperial", True),
            ("scientific_includes_units_param", "scientific", True),
        ]
    )
    @time_machine.travel("2026-07-21", tick=False)
    def test_units_param_only_sent_for_non_default_unit_system(self, _name, units, expect_param):
        result = _driver(units=units, start_date="2026-07-20").run(
            DAILY_ENDPOINT, [ScriptedResponse(json={"data": []})]
        )

        assert result.raised is None
        assert (result.requests[0].param("units") is not None) is expect_param
        if expect_param:
            assert result.requests[0].param("units") == units

    @time_machine.travel("2026-07-21", tick=False)
    def test_non_ok_status_raises(self):
        result = _driver(start_date="2026-07-20").run(DAILY_ENDPOINT, always(ScriptedResponse(status=500)))

        assert isinstance(result.raised, requests.HTTPError)
        assert set(result.paths) == {"/stations/daily"}


class TestSnapshotRows:
    @parameterized.expand(
        [
            (
                "station_meta_object_without_units",
                STATIONS_ENDPOINT,
                {"id": "10637", "country": "DE", "location": {"latitude": 50.05}},
                "/stations/meta",
                {"id": "10637", "station": None, "units": None},
                {"id": "10637", "country": "DE", "location": {"latitude": 50.05}, "station_id": "10637"},
            ),
            (
                "station_normals_with_units",
                NORMALS_ENDPOINT,
                [{"start": 1961, "end": 1990, "month": 1, "tavg": 33.0}],
                "/stations/normals",
                {"station": "10637", "id": None, "units": "imperial"},
                {"start": 1961, "end": 1990, "month": 1, "tavg": 33.0, "station_id": "10637"},
            ),
            (
                "point_normals_with_units",
                POINT_NORMALS_ENDPOINT,
                [{"start": 1991, "end": 2020, "month": 7, "tavg": 64.0}],
                "/point/normals",
                {"lat": "59.9127", "lon": "10.7461", "alt": "26", "station": None, "units": "imperial"},
                {
                    "start": 1991,
                    "end": 2020,
                    "month": 7,
                    "tavg": 64.0,
                    "latitude": 59.9127,
                    "longitude": 10.7461,
                    "altitude": 26,
                },
            ),
        ]
    )
    def test_request_and_row_shape(self, _name, endpoint_name, data, expected_path, expected_params, expected_row):
        result = _driver(units="imperial", locations="59.9127,10.7461,26").run(
            endpoint_name, [ScriptedResponse(json={"data": data})]
        )

        assert result.raised is None
        assert result.paths == [expected_path]
        assert {name: result.requests[0].param(name) for name in expected_params} == expected_params
        assert result.rows == [expected_row]

    def test_resume_skips_fetched_targets_and_tolerates_an_empty_response(self):
        result = _driver(station_ids="10637,71508,D1234").run(
            NORMALS_ENDPOINT,
            [ScriptedResponse(json={"data": []}), ScriptedResponse(json={"data": [{"month": 1}]})],
            resume_state=MeteostatResumeConfig(station_index=1, next_start=""),
        )

        assert result.raised is None
        assert result.params("station") == ["71508", "D1234"]
        assert result.rows == [{"month": 1, "station_id": "D1234"}]
        assert result.saved_states[-1] == MeteostatResumeConfig(station_index=3, next_start="")


class TestMeteostatSourceResponse:
    @parameterized.expand([(name,) for name in (HOURLY_ENDPOINT, DAILY_ENDPOINT, MONTHLY_ENDPOINT)])
    @time_machine.travel("2026-07-21", tick=False)
    def test_primary_keys_and_partitioning_per_endpoint(self, endpoint_name):
        endpoint = METEOSTAT_ENDPOINTS[endpoint_name]
        result = _driver(start_date="2026-07-22").run(endpoint_name, [])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint_name
        assert response.primary_keys == endpoint.primary_keys
        assert "station_id" in (response.primary_keys or [])
        assert response.partition_keys == [endpoint.date_field]
        assert response.sort_mode == "asc"


class TestValidateStation:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("not_found", 404, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name, status, expected_valid):
        script = always(ScriptedResponse(status=status)) if status == 500 else [ScriptedResponse(status=status)]
        with scripted_network(script) as network:
            is_valid, message = validate_station("key-123", "10637")

        assert {request.path for request in network.requests_log} == {"/stations/meta"}
        assert {request.param("id") for request in network.requests_log} == {"10637"}
        assert {request.headers["x-rapidapi-key"] for request in network.requests_log} == {"key-123"}
        assert is_valid is expected_valid
        if expected_valid:
            assert message is None
        else:
            assert message is not None

    def test_network_error_is_not_valid(self):
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            is_valid, message = validate_station("key-123", "10637")

        assert {request.path for request in network.requests_log} == {"/stations/meta"}
        assert is_valid is False
        assert message is not None and "Could not reach" in message
