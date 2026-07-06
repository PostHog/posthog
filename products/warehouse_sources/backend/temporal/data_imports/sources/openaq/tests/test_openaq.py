from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.openaq import openaq
from products.warehouse_sources.backend.temporal.data_imports.sources.openaq.openaq import (
    OpenAQResumeConfig,
    _build_url,
    _flatten_measurement,
    _flatten_sensor,
    _format_time_value,
    get_rows,
    validate_credentials,
)


class _FakeResumableManager:
    def __init__(self, state: OpenAQResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[OpenAQResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> OpenAQResumeConfig | None:
        return self._state

    def save_state(self, data: OpenAQResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, Any], endpoint: str, **kwargs
) -> list[dict]:
    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(openaq, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for table in get_rows(
        api_key="key",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(table.to_pylist())
    return rows


class TestFormatTimeValue:
    @parameterized.expand(
        [
            ("datetime_prefix_utc", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "datetime", "2026-03-04T02:58:14Z"),
            ("datetime_prefix_naive", datetime(2026, 3, 4, 2, 58, 14), "datetime", "2026-03-04T02:58:14Z"),
            ("date_prefix_from_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "date", "2026-03-04"),
            ("date_prefix_from_date", date(2026, 3, 4), "date", "2026-03-04"),
            ("datetime_prefix_from_date", date(2026, 3, 4), "datetime", "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T00:00:00Z", "datetime", "2026-03-04T00:00:00Z"),
        ]
    )
    def test_format_time_value(self, _name: str, value: Any, prefix: str, expected: str) -> None:
        # A wrong format 400s the measurement endpoint or silently drops the incremental filter.
        assert _format_time_value(value, prefix) == expected


class TestFlattenMeasurement:
    def test_lifts_sensor_id_and_period_start_for_primary_key(self) -> None:
        # The (sensor_id, datetime_from) pair is the composite primary key; both must reach the top level.
        item = {
            "value": 12.3,
            "parameter": {"id": 2, "name": "pm25", "units": "µg/m³"},
            "period": {
                "datetimeFrom": {"utc": "2026-01-01T00:00:00Z", "local": "2026-01-01T00:00:00+00:00"},
                "datetimeTo": {"utc": "2026-01-01T01:00:00Z"},
            },
            "coverage": {"percentComplete": 100},
            "flagInfo": {"hasFlags": False},
        }
        row = _flatten_measurement(item, sensor_id=99)
        assert row["sensor_id"] == 99
        assert row["datetime_from"] == "2026-01-01T00:00:00Z"
        assert row["datetime_to"] == "2026-01-01T01:00:00Z"
        assert row["value"] == 12.3
        assert row["parameter_id"] == 2
        assert row["parameter_name"] == "pm25"

    @parameterized.expand(
        [
            ("missing_period", {"value": 1.0}),
            ("null_period", {"value": 1.0, "period": None}),
            ("period_without_datetime", {"value": 1.0, "period": {"label": "x"}}),
        ]
    )
    def test_missing_period_yields_null_datetime_not_crash(self, _name: str, item: dict) -> None:
        # A sensor with a sparse/absent period must not blow up the whole fan-out.
        row = _flatten_measurement(item, sensor_id=1)
        assert row["sensor_id"] == 1
        assert row["datetime_from"] is None


class TestFlattenSensor:
    def test_attaches_location_context_and_flattens_parameter(self) -> None:
        location = {"id": 7, "name": "Station A", "timezone": "UTC", "country": {"code": "US"}}
        sensor = {"id": 55, "name": "pm25 sensor", "parameter": {"id": 2, "name": "pm25", "units": "µg/m³"}}
        row = _flatten_sensor(location, sensor)
        assert row["id"] == 55
        assert row["location_id"] == 7
        assert row["parameter_name"] == "pm25"
        assert row["timezone"] == "UTC"


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("server_error", 500, False)])
    def test_validate_credentials_maps_status(self, _name: str, status: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        with patch.object(openaq, "make_tracked_session", return_value=session):
            assert validate_credentials("key") is expected

    def test_validate_credentials_swallows_transport_error(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(openaq, "make_tracked_session", return_value=session):
            assert validate_credentials("key") is False


class TestFetchPageRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_statuses_retry_then_succeed(self, _name: str, status: int) -> None:
        bad = MagicMock()
        bad.status_code = status
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"results": []}

        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(openaq._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = openaq._fetch_page(session, "https://api.openaq.org/v3/parameters", {}, MagicMock())

        assert result == {"results": []}
        assert session.get.call_count == 2

    def test_client_error_raises_and_does_not_retry(self) -> None:
        error_response = requests.Response()
        error_response.status_code = 401
        response = MagicMock()
        response.status_code = 401
        response.ok = False
        response.raise_for_status.side_effect = requests.HTTPError(
            "401 Client Error: Unauthorized", response=error_response
        )

        session = MagicMock()
        session.get.return_value = response

        with patch.object(openaq._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(requests.HTTPError):
                openaq._fetch_page(session, "https://api.openaq.org/v3/parameters", {}, MagicMock())

        assert session.get.call_count == 1


class TestListPagination:
    def setup_method(self) -> None:
        # Shrink the page size so a 2-item first page forces a second fetch.
        self._orig = openaq.OPENAQ_PAGE_SIZE
        openaq.OPENAQ_PAGE_SIZE = 2

    def teardown_method(self) -> None:
        openaq.OPENAQ_PAGE_SIZE = self._orig

    def _list_url(self, path: str, page: int) -> str:
        params = {**openaq._LIST_SORT_PARAMS, "limit": openaq.OPENAQ_PAGE_SIZE, "page": page}
        return _build_url(f"{openaq.OPENAQ_BASE_URL}{path}", params)

    def test_pages_until_short_page_then_stops(self, monkeypatch: Any) -> None:
        pages = {
            self._list_url("/v3/parameters", 1): {"results": [{"id": 1}, {"id": 2}]},
            self._list_url("/v3/parameters", 2): {"results": [{"id": 3}]},
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, endpoint="parameters")
        assert [r["id"] for r in rows] == [1, 2, 3]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        pages = {
            # Page 1 must never be fetched when resuming from page 2.
            self._list_url("/v3/parameters", 2): {"results": [{"id": 3}]},
        }
        manager = _FakeResumableManager(OpenAQResumeConfig(page=2))
        rows = _collect(manager, monkeypatch, pages, endpoint="parameters")
        assert [r["id"] for r in rows] == [3]


class TestSensorsFanOut:
    def _loc_url(self, page: int) -> str:
        params = {**openaq._LIST_SORT_PARAMS, "limit": openaq.OPENAQ_PAGE_SIZE, "page": page}
        return _build_url(f"{openaq.OPENAQ_BASE_URL}/v3/locations", params)

    def test_materializes_one_row_per_embedded_sensor(self, monkeypatch: Any) -> None:
        pages = {
            self._loc_url(1): {
                "results": [
                    {"id": 1, "name": "L1", "sensors": [{"id": 10, "parameter": {"name": "pm25"}}]},
                    {"id": 2, "name": "L2", "sensors": [{"id": 20, "parameter": {"name": "o3"}}]},
                ]
            }
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, endpoint="sensors")
        assert [(r["id"], r["location_id"], r["parameter_name"]) for r in rows] == [
            (10, 1, "pm25"),
            (20, 2, "o3"),
        ]


class TestMeasurementFanOut:
    def _loc_url(self, page: int) -> str:
        params = {**openaq._LIST_SORT_PARAMS, "limit": openaq.OPENAQ_PAGE_SIZE, "page": page}
        return _build_url(f"{openaq.OPENAQ_BASE_URL}/v3/locations", params)

    def _sensor_url(self, sensor_id: int, page: int, extra: dict | None = None) -> str:
        params = {**(extra or {}), "limit": openaq.OPENAQ_PAGE_SIZE, "page": page}
        return _build_url(f"{openaq.OPENAQ_BASE_URL}/v3/sensors/{sensor_id}/measurements", params)

    def _measurement(self, dt: str, value: float) -> dict:
        return {"value": value, "parameter": {"name": "pm25"}, "period": {"datetimeFrom": {"utc": dt}}}

    def test_fans_out_over_every_sensor(self, monkeypatch: Any) -> None:
        pages = {
            self._loc_url(1): {
                "results": [{"id": 1, "sensors": [{"id": 10}, {"id": 11}]}],
            },
            self._sensor_url(10, 1): {"results": [self._measurement("2026-01-01T00:00:00Z", 5.0)]},
            self._sensor_url(11, 1): {"results": [self._measurement("2026-01-02T00:00:00Z", 6.0)]},
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, endpoint="measurements")
        assert [(r["sensor_id"], r["datetime_from"], r["value"]) for r in rows] == [
            (10, "2026-01-01T00:00:00Z", 5.0),
            (11, "2026-01-02T00:00:00Z", 6.0),
        ]

    def test_applies_incremental_datetime_filter(self, monkeypatch: Any) -> None:
        cutoff = datetime(2026, 1, 5, tzinfo=UTC)
        filtered_url = self._sensor_url(10, 1, extra={"datetime_from": "2026-01-05T00:00:00Z"})
        pages = {
            self._loc_url(1): {"results": [{"id": 1, "sensors": [{"id": 10}]}]},
            filtered_url: {"results": [self._measurement("2026-01-06T00:00:00Z", 7.0)]},
        }
        # The row is only reachable if the request carried datetime_from — proving the server-side filter is applied.
        rows = _collect(
            _FakeResumableManager(),
            monkeypatch,
            pages,
            endpoint="measurements",
            should_use_incremental_field=True,
            db_incremental_field_last_value=cutoff,
        )
        assert [r["datetime_from"] for r in rows] == ["2026-01-06T00:00:00Z"]

    def test_saves_bookmark_advancing_to_next_sensor(self, monkeypatch: Any) -> None:
        pages = {
            self._loc_url(1): {"results": [{"id": 1, "sensors": [{"id": 10}, {"id": 11}]}]},
            self._sensor_url(10, 1): {"results": [self._measurement("2026-01-01T00:00:00Z", 5.0)]},
            self._sensor_url(11, 1): {"results": [self._measurement("2026-01-02T00:00:00Z", 6.0)]},
        }
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, pages, endpoint="measurements")
        # After finishing sensor 10, the bookmark advances to sensor 11 so a crash resumes there.
        assert OpenAQResumeConfig(page=1, parent_sensor_id=11) in manager.saved

    def test_resume_skips_already_synced_sensors(self, monkeypatch: Any) -> None:
        pages = {
            self._loc_url(1): {"results": [{"id": 1, "sensors": [{"id": 10}, {"id": 11}]}]},
            # Sensor 10 must not be fetched again; only sensor 11 (the bookmark) is.
            self._sensor_url(11, 1): {"results": [self._measurement("2026-01-02T00:00:00Z", 6.0)]},
        }
        manager = _FakeResumableManager(OpenAQResumeConfig(page=1, parent_sensor_id=11))
        rows = _collect(manager, monkeypatch, pages, endpoint="measurements")
        assert [r["sensor_id"] for r in rows] == [11]
