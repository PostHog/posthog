from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.meteostat import (
    NO_STATIONS_ERROR,
    MeteostatResumeConfig,
    _coerce_date,
    _get_rows,
    _parse_station_ids,
    _parse_timestamp,
    meteostat_source,
    start_date_error,
    validate_station,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.settings import (
    DAILY_ENDPOINT,
    HOURLY_ENDPOINT,
    MAX_STATIONS,
    METEOSTAT_ENDPOINTS,
    MINIMUM_START_DATE,
    MONTHLY_ENDPOINT,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.meteostat"


def _response(status: int = 200, json_body: Any = None) -> mock.MagicMock:
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status
    response.json.return_value = json_body if json_body is not None else {}
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status} error", response=response)
    return response


def _manager(resume_state: Optional[MeteostatResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _run(
    endpoint_name: str,
    session: mock.MagicMock,
    manager: Optional[mock.MagicMock] = None,
    station_ids: str = "10637",
    units: str = "metric",
    start_date: Optional[str] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> list[list[dict[str, Any]]]:
    with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
        return list(
            _get_rows(
                api_key="key-123",
                station_ids=station_ids,
                endpoint=METEOSTAT_ENDPOINTS[endpoint_name],
                units=units,
                start_date=start_date,
                logger=mock.MagicMock(),
                resumable_source_manager=manager if manager is not None else _manager(),
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )
        )


def _requested_params(session: mock.MagicMock) -> list[dict[str, str]]:
    params = []
    for call in session.get.call_args_list:
        url = call.args[0]
        query = url.split("?", 1)[1]
        pairs = dict(pair.split("=", 1) for pair in query.split("&"))
        params.append(pairs)
    return params


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

    def test_parse_station_ids_bounds_split_regardless_of_input_size(self):
        # A pathological input with millions of commas must not make split() materialize
        # millions of parts before the caller's MAX_STATIONS check ever runs.
        station_ids = ",".join(str(i) for i in range(2_000_000))
        stations = _parse_station_ids(station_ids)
        assert len(stations) == MAX_STATIONS + 1
        assert stations[:5] == ["0", "1", "2", "3", "4"]

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


class TestGetRows:
    @freeze_time("2026-07-21")
    def test_single_window_rows_tagged_with_station_and_state_saved_after_yield(self):
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = _response(json_body={"data": [{"date": "2026-07-18", "tavg": 20.5}]})
        manager = _manager()

        batches = _run(DAILY_ENDPOINT, session, manager, station_ids="10637", start_date="2026-07-18")

        params = _requested_params(session)
        assert params == [{"station": "10637", "start": "2026-07-18", "end": "2026-07-21"}]
        assert len(batches) == 1
        row = batches[0][0]
        assert row["station_id"] == "10637"
        assert row["date"] == datetime(2026, 7, 18)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [MeteostatResumeConfig(station_index=0, next_start="2026-07-22")]

    @freeze_time("2026-07-21")
    def test_multiple_stations_are_each_queried_across_the_full_range(self):
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = _response(json_body={"data": [{"date": "2026-07-18", "tavg": 5.0}]})

        batches = _run(DAILY_ENDPOINT, session, station_ids="10637, 71508", start_date="2026-07-18")

        params = _requested_params(session)
        assert [p["station"] for p in params] == ["10637", "71508"]
        assert [batch[0]["station_id"] for batch in batches] == ["10637", "71508"]

    @freeze_time("2026-08-15")
    def test_long_range_is_chunked_into_contiguous_windows_within_the_vendor_cap(self):
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = _response(json_body={"data": []})

        _run(HOURLY_ENDPOINT, session, station_ids="10637", start_date="2026-06-01")

        params = _requested_params(session)
        # Hourly's documented cap is 30 days per request; each window must respect it.
        for entry in params:
            span = date.fromisoformat(entry["end"]) - date.fromisoformat(entry["start"])
            assert span.days <= 29
        # Windows are contiguous: each window starts the day after the previous one ends.
        for previous, current in zip(params, params[1:]):
            assert date.fromisoformat(current["start"]) == date.fromisoformat(previous["end"]) + timedelta(days=1)
        assert date.fromisoformat(params[-1]["end"]) == date(2026, 8, 15)

    @freeze_time("2026-07-21")
    def test_incremental_start_uses_overlap_window(self):
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = _response(json_body={"data": []})

        _run(
            DAILY_ENDPOINT,
            session,
            station_ids="10637",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 7, 15, tzinfo=UTC),
        )

        params = _requested_params(session)
        # Re-fetches a 7 day trailing overlap so late corrections get picked up; merge dedupes.
        assert params == [{"station": "10637", "start": "2026-07-08", "end": "2026-07-21"}]

    @freeze_time("2026-07-21")
    def test_resume_state_skips_completed_stations_and_resumes_the_current_one(self):
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = _response(json_body={"data": []})
        manager = _manager(resume_state=MeteostatResumeConfig(station_index=1, next_start="2026-07-19"))

        _run(DAILY_ENDPOINT, session, manager, station_ids="10637,71508", start_date="2026-01-01")

        params = _requested_params(session)
        # Station 0 already finished in a prior attempt; only station 1 is queried, resuming
        # from its saved cursor rather than restarting at start_date.
        assert params == [{"station": "71508", "start": "2026-07-19", "end": "2026-07-21"}]

    def test_raises_without_configured_stations(self):
        with pytest.raises(ValueError, match=NO_STATIONS_ERROR):
            _run(DAILY_ENDPOINT, mock.MagicMock(spec=requests.Session), station_ids="  ,  ")

    @freeze_time("2026-07-21")
    def test_station_count_is_capped_at_runtime(self):
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = _response(json_body={"data": []})
        station_ids = ",".join(str(i) for i in range(MAX_STATIONS + 5))

        _run(DAILY_ENDPOINT, session, station_ids=station_ids, start_date="2026-07-20")

        assert session.get.call_count == MAX_STATIONS

    @parameterized.expand(
        [
            ("metric_omits_units_param", "metric", False),
            ("imperial_includes_units_param", "imperial", True),
            ("scientific_includes_units_param", "scientific", True),
        ]
    )
    @freeze_time("2026-07-21")
    def test_units_param_only_sent_for_non_default_unit_system(self, _name, units, expect_param):
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = _response(json_body={"data": []})

        _run(DAILY_ENDPOINT, session, station_ids="10637", units=units, start_date="2026-07-20")

        params = _requested_params(session)
        assert ("units" in params[0]) is expect_param
        if expect_param:
            assert params[0]["units"] == units

    @freeze_time("2026-07-21")
    def test_non_ok_status_raises(self):
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = _response(status=500)

        with pytest.raises(requests.HTTPError):
            _run(DAILY_ENDPOINT, session, station_ids="10637", start_date="2026-07-20")

    @freeze_time("2026-07-21")
    def test_start_date_before_floor_is_clamped(self):
        # A too-old start_date is re-checked (not just rejected at credential validation) so a
        # previously stored configuration can't schedule a runaway backfill either.
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = _response(json_body={"data": []})

        _run(DAILY_ENDPOINT, session, station_ids="10637", start_date="0001-01-01")

        params = _requested_params(session)
        assert params[0]["start"] == MINIMUM_START_DATE.isoformat()


class TestMeteostatSourceResponse:
    @parameterized.expand([(name,) for name in (HOURLY_ENDPOINT, DAILY_ENDPOINT, MONTHLY_ENDPOINT)])
    def test_primary_keys_and_partitioning_per_endpoint(self, endpoint_name):
        endpoint = METEOSTAT_ENDPOINTS[endpoint_name]
        response = meteostat_source(
            api_key="key-123",
            station_ids="10637",
            units="metric",
            start_date=None,
            endpoint_name=endpoint_name,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(spec=ResumableSourceManager),
        )

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
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            make_session.return_value.get.return_value = _response(status=status)
            is_valid, message = validate_station("key-123", "10637")

        assert is_valid is expected_valid
        if expected_valid:
            assert message is None
        else:
            assert message is not None

    def test_network_error_is_not_valid(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            make_session.return_value.get.side_effect = requests.ConnectionError("boom")
            is_valid, message = validate_station("key-123", "10637")

        assert is_valid is False
        assert message is not None and "Could not reach" in message
