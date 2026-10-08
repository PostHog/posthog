import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.openaq import openaq
from products.warehouse_sources.backend.temporal.data_imports.sources.openaq.openaq import (
    OpenAQResumeConfig,
    _flatten_measurement,
    _format_time_value,
    openaq_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the openaq module.
OPENAQ_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.openaq.openaq.make_tracked_session"
)


def _response(
    results: list[dict[str, Any]] | None, *, status: int = 200, headers: dict[str, str] | None = None
) -> Response:
    resp = Response()
    resp.status_code = status
    resp.headers.update(headers or {})
    body: dict[str, Any] = {} if results is None else {"results": results}
    resp._content = json.dumps(body).encode()
    resp.url = "https://api.openaq.org/probe"
    return resp


def _make_manager(resume_state: OpenAQResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    manager.saved = []
    manager.save_state.side_effect = lambda state: manager.saved.append(state)
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's url + params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so a copy is snapshotted when each
    request is prepared rather than read after the run.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return openaq_source(
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


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
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("server_error", 500, False)])
    def test_validate_credentials_maps_status(self, _name: str, status: int, expected: bool) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status)
        with mock.patch(OPENAQ_SESSION_PATCH, return_value=session):
            assert validate_credentials("key") is expected


class TestRetryClassification:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_and_is_not_retried(self, MockSession) -> None:
        session = MockSession.return_value
        error = _response(None, status=401)
        error.url = "https://api.openaq.org/v3/parameters?limit=1000&page=1"
        _wire(session, [error])

        # 401 must fail loud (feeds the non-retryable credential message), not spin on retries.
        with pytest.raises(HTTPError, match="401 Client Error"):
            _rows(_source("parameters", _make_manager()))
        assert session.send.call_count == 1


class TestListPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_next_page_after_full_page(self, MockSession, monkeypatch) -> None:
        monkeypatch.setattr(openaq, "OPENAQ_PAGE_SIZE", 2)
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}, {"id": 2}]), _response([{"id": 3}])])

        manager = _make_manager()
        _rows(_source("parameters", manager))
        # After the first full page a checkpoint pointing at page 2 is saved; the short page saves nothing.
        assert OpenAQResumeConfig(page=2) in manager.saved


class TestSensorsFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_materializes_one_row_per_embedded_sensor(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    [
                        {"id": 1, "name": "L1", "sensors": [{"id": 10, "parameter": {"name": "pm25"}}]},
                        {"id": 2, "name": "L2", "sensors": [{"id": 20, "parameter": {"name": "o3"}}]},
                    ]
                )
            ],
        )

        rows = _rows(_source("sensors", _make_manager()))
        assert [(r["id"], r["location_id"], r["parameter_name"]) for r in rows] == [
            (10, 1, "pm25"),
            (20, 2, "o3"),
        ]


class TestMeasurementFanOut:
    def _measurement(self, dt: str, value: float) -> dict:
        return {"value": value, "parameter": {"name": "pm25"}, "period": {"datetimeFrom": {"utc": dt}}}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_applies_incremental_datetime_filter(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _response([{"id": 1, "sensors": [{"id": 10}]}]),
                _response([self._measurement("2026-01-06T00:00:00Z", 7.0)]),
            ],
        )

        rows = _rows(
            _source(
                "measurements",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 5, tzinfo=UTC),
            )
        )
        assert [r["datetime_from"] for r in rows] == ["2026-01-06T00:00:00Z"]
        # The per-sensor request carried the server-side datetime filter.
        sensor_req = next(s for s in snaps if "/sensors/10/measurements" in s["url"])
        assert sensor_req["params"]["datetime_from"] == "2026-01-05T00:00:00Z"
