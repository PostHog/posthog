from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.metaplane import (
    MetaplaneSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.metaplane import (
    EVALUATION_PAGE_LIMIT,
    MetaplaneResumeConfig,
    _format_datetime,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.settings import METAPLANE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.source import MetaplaneSource


def _driver() -> SourceDriver:
    return SourceDriver(MetaplaneSource(), MetaplaneSourceConfig(api_key="key"))


def _single_monitor_script(pages: list[Any]) -> list[ScriptedResponse]:
    return [
        ScriptedResponse(json=[{"id": "c1"}]),
        ScriptedResponse(json={"data": [{"id": "m1"}]}),
        *(ScriptedResponse(json=page) for page in pages),
    ]


def _evaluation(created_at: str, **extra: Any) -> dict[str, Any]:
    return {"createdAt": created_at, "result": 1.0, "passed": True, **extra}


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            ("naive_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (
                "microseconds_truncated_to_millis",
                datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC),
                "2026-01-15T10:30:45.123Z",
            ),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "2026-03-04T02:58:14.000Z", "2026-03-04T02:58:14.000Z"),
        ]
    )
    def test_format_datetime(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestMakeSession:
    def test_disables_sample_capture_and_redacts_key(self) -> None:
        # Metaplane response bodies carry free-form tenant data (monitor descriptions, custom SQL
        # config, error messages) the name-based scrubbers can't recognise, so sample capture must
        # stay off and the API key is redacted as defense in depth.
        with scripted_network([ScriptedResponse(json=[])]) as network:
            assert validate_credentials("mp-secret") is True
        assert network.session_options[0]["capture"] is False
        assert network.session_options[0]["redact_values"] == ("mp-secret",)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_code_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code, json=[])]) as network:
            assert validate_credentials("key") is expected
        assert network.requests_log[0].path == "/v1/connections"
        assert network.requests_log[0].headers["authorization"] == "key"

    def test_network_error_returns_invalid(self) -> None:
        with scripted_network([ConnectionResetError("boom")]) as network:
            assert validate_credentials("key") is False
        assert network.requests_log[0].path == "/v1/connections"


class TestConnectionsEndpoint:
    def test_yields_connection_rows(self) -> None:
        result = _driver().run("connections", [ScriptedResponse(json=[{"id": "c1"}, {"id": "c2"}])])
        assert result.raised is None
        assert result.items == [[{"id": "c1"}, {"id": "c2"}]]


class TestMonitorsEndpoint:
    def test_deleted_connection_is_skipped(self) -> None:
        # c1 404s (deleted between enumeration and fetch); the sync must continue with c2.
        result = _driver().run(
            "monitors",
            [
                ScriptedResponse(json=[{"id": "c1"}, {"id": "c2"}]),
                ScriptedResponse(status=404, json={}),
                ScriptedResponse(json={"data": [{"id": "m2"}]}),
            ],
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["m2"]
        assert result.paths == [
            "/v1/connections",
            "/v1/monitors/connection/c1",
            "/v1/monitors/connection/c2",
        ]


class TestConnectionSyncStatusesEndpoint:
    def test_connection_without_status_is_skipped(self) -> None:
        result = _driver().run(
            "connection_sync_statuses",
            [
                ScriptedResponse(json=[{"id": "c1"}, {"id": "c2"}]),
                ScriptedResponse(status=404, json={}),
                ScriptedResponse(json={"status": "SUCCEEDED", "connectionId": "c2"}),
            ],
        )
        assert result.raised is None
        assert [row["connectionId"] for row in result.rows] == ["c2"]


class TestEvaluationHistory:
    def test_rows_carry_injected_monitor_id(self) -> None:
        result = _driver().run(
            "monitor_evaluations", _single_monitor_script([[_evaluation("2026-01-01T00:00:00.000Z")]])
        )
        assert result.raised is None
        assert result.items == [
            [{"createdAt": "2026-01-01T00:00:00.000Z", "result": 1.0, "passed": True, "monitorId": "m1"}]
        ]

    def test_full_page_requests_next_page_from_last_created_at(self) -> None:
        full_page = [_evaluation(f"2026-01-01T00:00:{i:02d}.000Z") for i in range(EVALUATION_PAGE_LIMIT)]
        result = _driver().run(
            "monitor_evaluations",
            _single_monitor_script([full_page, [_evaluation("2026-01-01T01:00:00.000Z")]]),
        )

        assert result.raised is None
        bodies = [request.json() for request in result.requests if request.method == "POST"]
        assert "createdAt" not in bodies[0]
        assert bodies[0]["sortOrder"] == "ASC"
        assert bodies[1]["createdAt"] == full_page[-1]["createdAt"]
        # State is saved after yielding the full page so a crash re-yields it (merge dedupes).
        assert result.saved_states == [MetaplaneResumeConfig(monitor_id="m1", cursor=full_page[-1]["createdAt"])]

    def test_non_advancing_cursor_stops_pagination(self) -> None:
        # A full page of identical timestamps would otherwise re-request the same page forever.
        same_ts_page = [_evaluation("2026-01-01T00:00:00.000Z") for _ in range(EVALUATION_PAGE_LIMIT)]
        result = _driver().run(
            "monitor_evaluations",
            _single_monitor_script([same_ts_page]),
            resume_state=MetaplaneResumeConfig(monitor_id="m1", cursor="2026-01-01T00:00:00.000Z"),
        )

        assert result.raised is None
        assert result.paths.count("/v1/monitors/evaluation-history/m1") == 1
        assert len(result.items) == 1

    def test_incremental_watermark_seeds_initial_cursor(self) -> None:
        result = _driver().run(
            "monitor_evaluations",
            _single_monitor_script([[_evaluation("2026-03-05T00:00:00.000Z")]]),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert result.raised is None
        assert next(request for request in result.requests if request.method == "POST").json()["createdAt"] == (
            "2026-03-04T02:58:14.000Z"
        )

    def test_monitor_without_history_is_skipped(self) -> None:
        # A monitor that was deleted (or never modeled) 404s; the sync continues with the rest.
        result = _driver().run(
            "monitor_evaluations",
            [
                ScriptedResponse(json=[{"id": "c1"}]),
                ScriptedResponse(json={"data": [{"id": "m1"}, {"id": "m2"}]}),
                ScriptedResponse(status=404, json={}),
                ScriptedResponse(json=[_evaluation("2026-01-02T00:00:00.000Z")]),
            ],
        )
        assert result.raised is None
        assert [row["monitorId"] for row in result.rows] == ["m2"]


class TestMetaplaneSourceResponse:
    @parameterized.expand([(name,) for name in sorted(METAPLANE_ENDPOINTS)])
    def test_source_response_matches_endpoint_settings(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])
        assert result.raised is None
        response = result.response
        assert response is not None
        config = METAPLANE_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Only the monitor fan-out defers the watermark to job end.
        assert response.sort_mode == ("desc" if endpoint == "monitor_evaluations" else "asc")
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
