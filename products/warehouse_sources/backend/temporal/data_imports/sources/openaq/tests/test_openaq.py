from datetime import UTC, date, datetime
from typing import Any

from pytest import MonkeyPatch

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openaq import OpenAQSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.openaq import openaq
from products.warehouse_sources.backend.temporal.data_imports.sources.openaq.openaq import (
    OpenAQResumeConfig,
    _flatten_measurement,
    _format_time_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openaq.source import OpenAQSource


def _driver() -> SourceDriver:
    return SourceDriver(OpenAQSource(), OpenAQSourceConfig(api_key="key"))


def _page(results: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"results": results})


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


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_validate_credentials_maps_status(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("key") is expected
        assert {request.path for request in network.requests_log} == {"/v3/parameters"}
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["x-api-key"] == "key"


class TestRetryClassification:
    def test_client_error_raises_and_is_not_retried(self) -> None:
        # 401 must fail loud (feeds the non-retryable credential message), not spin on retries.
        result = _driver().run("parameters", [ScriptedResponse(status=401, json={})])
        assert isinstance(result.raised, HTTPError)
        assert "401 Client Error" in str(result.raised)
        assert result.paths == ["/v3/parameters"]


class TestListPagination:
    def test_checkpoints_next_page_after_full_page(self, monkeypatch: MonkeyPatch) -> None:
        monkeypatch.setattr(openaq, "OPENAQ_PAGE_SIZE", 2)
        result = _driver().run("parameters", [_page([{"id": 1}, {"id": 2}]), _page([{"id": 3}])])
        # After the first full page a checkpoint pointing at page 2 is saved; the short page saves nothing.
        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert result.params("page") == ["1", "2"]
        assert OpenAQResumeConfig(page=2) in result.saved_states


class TestSensorsFanOut:
    def test_materializes_one_row_per_embedded_sensor(self) -> None:
        result = _driver().run(
            "sensors",
            [
                _page(
                    [
                        {"id": 1, "name": "L1", "sensors": [{"id": 10, "parameter": {"name": "pm25"}}]},
                        {"id": 2, "name": "L2", "sensors": [{"id": 20, "parameter": {"name": "o3"}}]},
                    ]
                )
            ],
        )

        assert result.raised is None
        assert [(r["id"], r["location_id"], r["parameter_name"]) for r in result.rows] == [
            (10, 1, "pm25"),
            (20, 2, "o3"),
        ]


class TestMeasurementFanOut:
    def _measurement(self, dt: str, value: float) -> dict[str, Any]:
        return {"value": value, "parameter": {"name": "pm25"}, "period": {"datetimeFrom": {"utc": dt}}}

    def test_applies_incremental_datetime_filter(self) -> None:
        result = _driver().run(
            "measurements",
            [
                _page([{"id": 1, "sensors": [{"id": 10}]}]),
                _page([self._measurement("2026-01-06T00:00:00Z", 7.0)]),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 5, tzinfo=UTC),
        )
        assert result.raised is None
        assert [r["datetime_from"] for r in result.rows] == ["2026-01-06T00:00:00Z"]
        # The per-sensor request carried the server-side datetime filter.
        sensor_req = next(request for request in result.requests if "/sensors/10/measurements" in request.path)
        assert sensor_req.param("datetime_from") == "2026-01-05T00:00:00Z"
