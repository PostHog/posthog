from datetime import date
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cimis import cimis
from products.warehouse_sources.backend.temporal.data_imports.sources.cimis.cimis import (
    _date_windows,
    _flatten_record,
    _iter_data_records,
    cimis_source,
    get_rows,
    parse_targets,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cimis.settings import (
    CIMIS_ENDPOINTS,
    CIMIS_RECORD_CAP,
)


class TestParseTargets:
    @parameterized.expand(
        [
            ("none", None, []),
            ("empty", "", []),
            ("single", "2", ["2"]),
            ("multiple", "2,8,127", ["2", "8", "127"]),
            ("whitespace_and_blanks", " 2 , ,8 ,", ["2", "8"]),
        ]
    )
    def test_parse_targets(self, _name: str, raw: str | None, expected: list[str]) -> None:
        assert parse_targets(raw) == expected


class TestFlattenRecord:
    def test_flattens_measurement_objects_into_scalar_columns(self) -> None:
        record = {
            "Date": "2023-01-01",
            "Station": "2",
            "Scope": "daily",
            "DayAirTmpAvg": {"Value": "50.1", "Qc": " ", "Unit": "(F)"},
        }
        flat = _flatten_record(record)
        assert flat["Date"] == "2023-01-01"
        assert flat["Station"] == "2"
        assert flat["DayAirTmpAvg_Value"] == "50.1"
        assert flat["DayAirTmpAvg_Qc"] == " "
        assert flat["DayAirTmpAvg_Unit"] == "(F)"
        # The nested object itself should not survive as a column.
        assert "DayAirTmpAvg" not in flat

    def test_leaves_non_measurement_values_untouched(self) -> None:
        # ZipCodes is a list, not a {Value, Qc, Unit} measurement object, so it passes through.
        record = {"Station": "2", "ZipCodes": ["93624"]}
        flat = _flatten_record(record)
        assert flat["ZipCodes"] == ["93624"]


class TestDateWindows:
    def test_single_day_windows(self) -> None:
        windows = list(_date_windows(date(2023, 1, 1), date(2023, 1, 3), 1))
        assert windows == [
            (date(2023, 1, 1), date(2023, 1, 1)),
            (date(2023, 1, 2), date(2023, 1, 2)),
            (date(2023, 1, 3), date(2023, 1, 3)),
        ]

    def test_multi_day_windows_clamp_to_end(self) -> None:
        windows = list(_date_windows(date(2023, 1, 1), date(2023, 1, 5), 2))
        assert windows == [
            (date(2023, 1, 1), date(2023, 1, 2)),
            (date(2023, 1, 3), date(2023, 1, 4)),
            (date(2023, 1, 5), date(2023, 1, 5)),
        ]

    def test_single_window_when_range_smaller_than_window(self) -> None:
        windows = list(_date_windows(date(2023, 1, 1), date(2023, 1, 2), 30))
        assert windows == [(date(2023, 1, 1), date(2023, 1, 2))]


class TestIterDataRecords:
    def test_iterates_records_across_providers_and_flattens(self) -> None:
        payload = {
            "Data": {
                "Providers": [
                    {"Name": "cimis", "Records": [{"Date": "2023-01-01", "DayEto": {"Value": "0.05"}}]},
                    {"Name": "scs", "Records": [{"Date": "2023-01-02", "DayEto": {"Value": "0.06"}}]},
                ]
            }
        }
        rows = list(_iter_data_records(payload))
        assert [r["Date"] for r in rows] == ["2023-01-01", "2023-01-02"]
        assert rows[0]["DayEto_Value"] == "0.05"

    def test_empty_payload_yields_nothing(self) -> None:
        assert list(_iter_data_records({})) == []


def _data_payload(station: str, day: str) -> dict[str, Any]:
    return {
        "Data": {
            "Providers": [
                {"Name": "cimis", "Records": [{"Date": day, "Station": station, "DayEto": {"Value": "0.05"}}]}
            ]
        }
    }


class TestGetRowsMetadata:
    def test_metadata_endpoint_yields_response_key_rows(self, monkeypatch: Any) -> None:
        captured: list[str] = []

        def fake_fetch(_session: Any, url: str, _logger: Any) -> dict[str, Any]:
            captured.append(url)
            return {"Stations": [{"StationNbr": "2"}, {"StationNbr": "8"}]}

        monkeypatch.setattr(cimis, "_fetch", fake_fetch)
        batches = list(get_rows(endpoint="stations", app_key="k", targets=[], unit_of_measure="E", logger=mock.Mock()))

        assert batches == [[{"StationNbr": "2"}, {"StationNbr": "8"}]]
        assert len(captured) == 1
        assert "/station" in captured[0]


class TestGetRowsData:
    def test_data_endpoint_requires_targets(self) -> None:
        with pytest.raises(ValueError):
            list(get_rows(endpoint="daily_data", app_key="k", targets=[], unit_of_measure="E", logger=mock.Mock()))

    @freeze_time("2023-01-03 12:00:00")
    def test_daily_full_refresh_windows_from_epoch(self, monkeypatch: Any) -> None:
        urls: list[str] = []

        def fake_fetch(_session: Any, url: str, _logger: Any) -> dict[str, Any]:
            urls.append(url)
            return _data_payload("2", "2023-01-01")

        monkeypatch.setattr(cimis, "_fetch", fake_fetch)
        # Few targets and a large per-request cap means a single window covers the whole range.
        batches = list(
            get_rows(endpoint="daily_data", app_key="k", targets=["2"], unit_of_measure="E", logger=mock.Mock())
        )
        assert len(batches) >= 1
        assert all("startDate=" in u and "endDate=" in u for u in urls)
        # No request may reach into the future.
        assert all("endDate=2023-01-03" in u for u in urls[-1:])

    @freeze_time("2023-01-10 12:00:00")
    def test_daily_incremental_starts_from_last_value(self, monkeypatch: Any) -> None:
        urls: list[str] = []

        def fake_fetch(_session: Any, url: str, _logger: Any) -> dict[str, Any]:
            urls.append(url)
            return _data_payload("2", "2023-01-08")

        monkeypatch.setattr(cimis, "_fetch", fake_fetch)
        list(
            get_rows(
                endpoint="daily_data",
                app_key="k",
                targets=["2"],
                unit_of_measure="E",
                logger=mock.Mock(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2023, 1, 8),
            )
        )
        # The first window must begin at the saved watermark, not the epoch.
        assert "startDate=2023-01-08" in urls[0]

    @freeze_time("2023-01-02 12:00:00")
    def test_no_requests_when_watermark_in_future(self, monkeypatch: Any) -> None:
        urls: list[str] = []

        def fake_fetch(_session: Any, url: str, _logger: Any) -> dict[str, Any]:
            urls.append(url)
            return _data_payload("2", "2023-01-01")

        monkeypatch.setattr(cimis, "_fetch", fake_fetch)
        batches = list(
            get_rows(
                endpoint="daily_data",
                app_key="k",
                targets=["2"],
                unit_of_measure="E",
                logger=mock.Mock(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2030, 1, 1),
            )
        )
        assert batches == []
        assert urls == []

    @freeze_time("2020-01-01 12:00:00")
    def test_hourly_with_many_targets_keeps_each_request_under_cap(self, monkeypatch: Any) -> None:
        # 100 hourly targets over a single day would be 2400 records — over the cap — so the source
        # must split the target set and keep the date window at a single day.
        seen_requests: list[tuple[str, str, int]] = []

        def fake_fetch(_session: Any, url: str, _logger: Any) -> dict[str, Any]:
            # Parse start/end + target count out of the URL to assert the per-request volume.
            params = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
            n_targets = len(params["targets"].split("%2C")) if "%2C" in params["targets"] else 1
            seen_requests.append((params["startDate"], params["endDate"], n_targets))
            return _data_payload("1", "2019-12-31")

        monkeypatch.setattr(cimis, "_fetch", fake_fetch)
        targets = [str(i) for i in range(1, 101)]
        # Single-day range so we only probe the target-splitting dimension.
        with mock.patch.object(cimis, "CIMIS_DATA_EPOCH", "2019-12-31"):
            list(
                get_rows(endpoint="hourly_data", app_key="k", targets=targets, unit_of_measure="E", logger=mock.Mock())
            )

        assert seen_requests, "expected at least one request"
        for _start, _end, n_targets in seen_requests:
            # 24 records/day/target * n_targets * window_days(=1) must stay under the cap.
            assert n_targets * 24 <= CIMIS_RECORD_CAP


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        response = mock.Mock(spec=requests.Response)
        response.status_code = status
        session = mock.Mock()
        session.get.return_value = response

        with mock.patch.object(cimis, "make_tracked_session", return_value=session):
            ok, _msg = validate_credentials("appkey", ["2"], mock.Mock())
        assert ok is expected

    def test_unreachable_api_is_not_valid(self) -> None:
        session = mock.Mock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch.object(cimis, "make_tracked_session", return_value=session):
            ok, msg = validate_credentials("appkey", [], mock.Mock())
        assert ok is False
        assert msg is not None


class TestCimisSourceResponse:
    @parameterized.expand(
        [
            ("daily_data", ["Station", "Date"], "datetime"),
            ("hourly_data", ["Station", "Date", "Hour"], "datetime"),
            ("stations", ["StationNbr"], None),
            ("station_zipcodes", ["StationNbr", "ZipCode"], None),
            ("spatial_zipcodes", ["ZipCode"], None),
        ]
    )
    def test_source_response_shape(self, endpoint: str, primary_keys: list[str], partition_mode: str | None) -> None:
        response = cimis_source(endpoint=endpoint, app_key="k", targets=["2"], unit_of_measure="E", logger=mock.Mock())
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_mode == partition_mode
        assert response.sort_mode == "asc"
        if partition_mode == "datetime":
            assert response.partition_keys == [CIMIS_ENDPOINTS[endpoint].partition_key]
            assert response.partition_format == "month"
