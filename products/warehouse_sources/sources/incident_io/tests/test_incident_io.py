from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.incidentio import (
    IncidentIoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io import (
    IncidentIoResumeConfig,
    _build_params,
    _build_url,
    _format_filter_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.settings import (
    ENDPOINTS,
    INCIDENT_IO_API_VERSION_V1,
    INCIDENT_IO_API_VERSION_V3,
    INCIDENT_IO_DEFAULT_API_VERSION,
    INCIDENT_IO_ENDPOINTS,
    endpoints_for_version,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.source import IncidentIoSource


def _page_body(data_key: str, items: list[dict[str, Any]], after: str | None) -> dict[str, Any]:
    return {data_key: items, "pagination_meta": {"after": after, "page_size": 250}}


def _driver() -> SourceDriver:
    return SourceDriver(IncidentIoSource(), IncidentIoSourceConfig(api_key="key"))


class TestFormatFilterValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (True, None),
            (datetime(2024, 5, 1, 12, 30, tzinfo=UTC), "2024-05-01"),
            (datetime(2024, 5, 1, 12, 30), "2024-05-01"),
            (date(2024, 5, 1), "2024-05-01"),
            ("2024-05-01T12:30:00Z", "2024-05-01"),
            ("2024-05-01T12:30:00+00:00", "2024-05-01"),
            ("2024-05-01", "2024-05-01"),
            ("not-a-date", None),
            (1700000000, None),
        ],
    )
    def test_format_filter_value(self, value, expected):
        assert _format_filter_value(value) == expected


class TestBuildParams:
    def test_incremental_filter_included_when_set(self):
        params = _build_params(INCIDENT_IO_ENDPOINTS["incidents"], "updated_at", "2024-05-01")
        assert params["updated_at[gte]"] == "2024-05-01"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [
            (200, True),
            (401, False),
            (403, True),
            (500, False),
        ],
    )
    def test_status_mapping_at_source_create(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, _ = validate_credentials("key", INCIDENT_IO_DEFAULT_API_VERSION)

        assert is_valid is expected_valid
        assert {request.path for request in network.requests_log} == {"/v2/incidents"}

    @pytest.mark.parametrize(
        "api_version, schema_name, expected_url",
        [
            (INCIDENT_IO_API_VERSION_V3, "severities", "https://api.incident.io/v1/severities"),
            (INCIDENT_IO_API_VERSION_V1, "follow_ups", "https://api.incident.io/v2/follow_ups?page_size=1"),
            (INCIDENT_IO_API_VERSION_V3, "follow_ups", "https://api.incident.io/v3/follow_ups?page_size=1"),
        ],
    )
    def test_probe_url_per_schema(self, api_version: str, schema_name: str, expected_url: str) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("key", api_version, schema_name=schema_name)

        assert [request.url for request in network.requests_log] == [expected_url]

    @pytest.mark.parametrize(
        "schema_name, parent_key, parent_rows, child_status, expected_urls, expected_valid",
        [
            (
                "catalog_entries",
                "catalog_types",
                [{"id": "T1"}],
                403,
                [
                    "https://api.incident.io/v3/catalog_types",
                    "https://api.incident.io/v3/catalog_types",
                    "https://api.incident.io/v3/catalog_entries?catalog_type_id=T1&page_size=1",
                ],
                False,
            ),
            (
                "custom_field_options",
                "custom_fields",
                [{"id": "F1"}],
                200,
                [
                    "https://api.incident.io/v2/custom_fields",
                    "https://api.incident.io/v2/custom_fields",
                    "https://api.incident.io/v1/custom_field_options?custom_field_id=F1&page_size=1",
                ],
                True,
            ),
            # Schedule entries take no page-size param, so the child probe sends only the parent id.
            (
                "schedule_entries",
                "schedules",
                [{"id": "S1"}],
                200,
                [
                    "https://api.incident.io/v2/schedules?page_size=1",
                    "https://api.incident.io/v2/schedules",
                    "https://api.incident.io/v2/schedule_entries?schedule_id=S1",
                ],
                True,
            ),
            # Workloads take no page-size param, so the child probe sends only the parent incident id.
            (
                "incident_participant_workloads",
                "incidents",
                [{"id": "I1"}],
                403,
                [
                    "https://api.incident.io/v2/incidents?page_size=1",
                    "https://api.incident.io/v2/incidents",
                    "https://api.incident.io/v2/incident_participant_workloads?incident_id=I1",
                ],
                False,
            ),
            # No parent row to bind, so the child scope can't be probed and the parent probe decides.
            (
                "catalog_entries",
                "catalog_types",
                [],
                403,
                ["https://api.incident.io/v3/catalog_types", "https://api.incident.io/v3/catalog_types"],
                True,
            ),
        ],
    )
    def test_fanout_schema_probes_parent_then_child(
        self,
        schema_name: str,
        parent_key: str,
        parent_rows: list[dict[str, Any]],
        child_status: int,
        expected_urls: list[str],
        expected_valid: bool,
    ) -> None:
        answers = [
            ScriptedResponse(json={parent_key: parent_rows}),
            ScriptedResponse(json={parent_key: parent_rows}),
            ScriptedResponse(status=child_status),
        ]
        with scripted_network(answers) as network:
            is_valid, error = validate_credentials("key", INCIDENT_IO_DEFAULT_API_VERSION, schema_name=schema_name)

        assert [request.url for request in network.requests_log] == expected_urls
        assert is_valid is expected_valid
        if not expected_valid:
            assert error is not None and schema_name in error

    def test_swallows_network_exceptions(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))) as network:
            is_valid, error = validate_credentials("key", INCIDENT_IO_DEFAULT_API_VERSION)

        assert is_valid is False
        assert error is not None
        assert {request.path for request in network.requests_log} == {"/v2/incidents"}


class TestGetRows:
    @pytest.mark.parametrize(
        "api_version, expected_path, pages",
        [
            # v2 returns every follow-up in one unpaginated response.
            (INCIDENT_IO_API_VERSION_V1, "/v2/follow_ups", [{"follow_ups": [{"id": "01A"}, {"id": "01B"}]}]),
            (
                INCIDENT_IO_API_VERSION_V3,
                "/v3/follow_ups",
                [
                    _page_body("follow_ups", [{"id": "01A", "category": {"id": "C1"}}], "01A"),
                    _page_body("follow_ups", [{"id": "01B", "category": None}], None),
                ],
            ),
        ],
    )
    def test_follow_ups_path_per_version(
        self, api_version: str, expected_path: str, pages: list[dict[str, Any]]
    ) -> None:
        result = _driver().run("follow_ups", [ScriptedResponse(json=page) for page in pages], api_version=api_version)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["01A", "01B"]
        assert set(result.paths) == {expected_path}

    def test_unknown_api_version_raises(self) -> None:
        result = _driver().run("follow_ups", [], api_version="v2")

        assert isinstance(result.raised, ValueError)
        assert "Unsupported incident.io API version" in str(result.raised)
        assert result.requests == []

    def test_resumes_from_saved_state_and_preserves_filters(self) -> None:
        resume_url = _build_url(
            "/v2/incidents",
            {"page_size": 250, "sort_by": "created_at_oldest_first", "updated_at[gte]": "2024-05-01", "after": "01B"},
        )
        result = _driver().run(
            "incidents",
            [
                ScriptedResponse(json=_page_body("incidents", [{"id": "01C"}], "01C")),
                ScriptedResponse(json=_page_body("incidents", [], None)),
            ],
            resume_state=IncidentIoResumeConfig(next_url=resume_url),
        )

        assert result.raised is None
        # First request replays the saved cursor and keeps the original chain's filter.
        assert result.params("after")[0] == "01B"
        assert result.params("updated_at[gte]")[0] == "2024-05-01"
        # The next page swaps in the new cursor but keeps the filter.
        assert result.params("after")[1] == "01C"
        assert result.params("updated_at[gte]")[1] == "2024-05-01"
        assert any("after=01C" in state.next_url for state in result.saved_states if state.next_url)

    @pytest.mark.parametrize(
        "inputs, expected_updated_at_gte",
        [
            ({}, None),
            (
                {"incremental_field": "updated_at", "db_incremental_field_last_value": "2026-05-01T10:15:00Z"},
                "2026-05-01",
            ),
            (
                {
                    "incremental_field": "updated_at",
                    "should_use_incremental_field": False,
                    "db_incremental_field_last_value": "2026-05-01T10:15:00Z",
                },
                None,
            ),
        ],
    )
    def test_actions_incremental_request_shaping(
        self, inputs: dict[str, Any], expected_updated_at_gte: str | None
    ) -> None:
        result = _driver().run(
            "actions",
            [
                ScriptedResponse(json=_page_body("actions", [{"id": "01A"}], "01A")),
                ScriptedResponse(json=_page_body("actions", [{"id": "01B"}], None)),
            ],
            **inputs,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["01A", "01B"]
        assert set(result.paths) == {"/v3/actions"}
        assert result.params("after") == [None, "01A"]
        assert result.params("updated_at[gte]") == [expected_updated_at_gte] * 2
        assert result.params("page_size") == ["250", "250"]

    def test_alert_sources_drop_secret_token(self) -> None:
        body = {"alert_sources": [{"id": "01A", "name": "Datadog", "secret_token": "not-a-real-token"}]}
        result = _driver().run("alert_sources", [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.rows == [{"id": "01A", "name": "Datadog"}]
        # The raw body still carries the token, so it must never reach HTTP sample capture.
        assert result.session_options[0]["capture"] is False

    def test_raises_on_client_error(self) -> None:
        result = _driver().run("incidents", [ScriptedResponse(status=404, json={})])

        assert isinstance(result.raised, Exception)
        assert result.paths == ["/v2/incidents"]


class TestFanout:
    @time_machine.travel(datetime(2026, 3, 2, 12, 0, tzinfo=UTC), tick=False)
    def test_schedule_entries_resume_keeps_original_window(self) -> None:
        window = {"entry_window_start": "2025-03-01T12:00:00Z", "entry_window_end": "2026-03-31T12:00:00Z"}
        result = _driver().run(
            "schedule_entries",
            [
                ScriptedResponse(json={"schedules": [{"id": "S1"}], "pagination_meta": {"page_size": 250}}),
                ScriptedResponse(json={"schedule_entries": {"final": [{"fingerprint": "F1"}]}}),
            ],
            resume_state=IncidentIoResumeConfig(
                fanout_state={
                    "completed": [],
                    "current": "/v2/schedule_entries?schedule_id=S1",
                    "child_state": {"cursor": "opaque-1"},
                },
                window_params=window,
            ),
        )

        assert result.raised is None
        assert result.requests[1].param("entry_window_start") == "opaque-1"
        assert result.requests[1].param("entry_window_end") == "2026-03-31T12:00:00Z"

    @pytest.mark.parametrize(
        "workload_row, expected_user_id",
        [
            ({"user": {"id": "U1", "name": "Example User"}, "participant_type": "responder"}, "U1"),
            ({"user": None, "participant_type": "observer"}, None),
            ({"participant_type": "observer"}, None),
        ],
    )
    def test_incident_participant_workloads_rows_carry_their_keys(
        self, workload_row: dict[str, Any], expected_user_id: str | None
    ) -> None:
        result = _driver().run(
            "incident_participant_workloads",
            [
                ScriptedResponse(json=_page_body("incidents", [{"id": "I1"}], "I1")),
                ScriptedResponse(
                    json={
                        "incident_participant_workloads": [workload_row],
                        "metadata": {"data_synced_at": "2026-05-01T10:00:00Z"},
                    }
                ),
                ScriptedResponse(json=_page_body("incidents", [{"id": "I2"}], None)),
                ScriptedResponse(json={"incident_participant_workloads": [], "metadata": {}}),
            ],
        )

        assert result.raised is None
        assert [(row["incident_id"], row["user_id"]) for row in result.rows] == [("I1", expected_user_id)]
        assert result.rows[0]["participant_type"] == workload_row["participant_type"]
        assert result.paths == [
            "/v2/incidents",
            "/v2/incident_participant_workloads",
            "/v2/incidents",
            "/v2/incident_participant_workloads",
        ]
        incident_requests = [request for request in result.requests if request.path == "/v2/incidents"]
        assert [request.param("after") for request in incident_requests] == [None, "I1"]
        assert {request.param("sort_by") for request in incident_requests} == {"created_at_oldest_first"}
        workload_requests = [request for request in result.requests if request.path != "/v2/incidents"]
        assert [request.param("incident_id") for request in workload_requests] == ["I1", "I2"]
        assert all(request.param("page_size") is None for request in workload_requests)


class TestIncidentIoSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = INCIDENT_IO_ENDPOINTS[endpoint]
        data_key = config.fanout.parent_name if config.fanout else config.data_key
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={data_key: [], "pagination_meta": {"after": None}})],
        )

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize(
        "config",
        [
            config
            for version in (INCIDENT_IO_API_VERSION_V1, INCIDENT_IO_API_VERSION_V3)
            for config in endpoints_for_version(version).values()
        ],
    )
    def test_endpoint_paths_are_versioned(self, config):
        assert config.path.startswith(("/v1/", "/v2/", "/v3/"))
