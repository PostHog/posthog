import json
from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zero import ZeroSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zero.source import ZeroSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zero.zero import (
    ZeroResumeConfig,
    _build_where,
    _format_zero_datetime,
    get_resource,
    resolve_workspace_id,
)

WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"


def _make_http_response(body: dict[str, Any] | None, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body if body is not None else {})


class TestFormatZeroDatetime:
    def test_date_is_combined_with_midnight_utc(self) -> None:
        assert _format_zero_datetime(date(2026, 1, 1)) == "2026-01-01T00:00:00+00:00"

    def test_string_value_passes_through(self) -> None:
        assert _format_zero_datetime("2026-01-01T00:00:00Z") == "2026-01-01T00:00:00Z"


class TestBuildWhere:
    def test_workspace_and_date_filter_combined(self) -> None:
        convert = _build_where(WORKSPACE_ID, "updatedAt")
        result = json.loads(convert(datetime(2026, 1, 1, tzinfo=UTC)))
        assert result == {
            "workspaceId": WORKSPACE_ID,
            "updatedAt": {"$gt": "2026-01-01T00:00:00+00:00"},
        }

    def test_no_date_field_never_adds_a_date_filter(self) -> None:
        convert = _build_where(WORKSPACE_ID, None)
        result = json.loads(convert(datetime(2026, 1, 1, tzinfo=UTC)))
        assert result == {"workspaceId": WORKSPACE_ID}


class TestGetResource:
    @parameterized.expand(
        [
            ("Companies", "companies", "/api/companies"),
            ("Contacts", "contacts", "/api/contacts"),
            ("Deals", "deals", "/api/deals"),
            ("Pipelines", "pipelines", "/api/pipelines"),
            ("PipelineStages", "pipeline_stages", "/api/pipelineStages"),
            ("Notes", "notes", "/api/notes"),
            ("Tasks", "tasks", "/api/tasks"),
            ("Meetings", "meetings", "/api/calendarEvents"),
            ("Memberships", "memberships", "/api/memberships"),
            ("Workspaces", "workspaces", "/api/workspaces"),
            ("Users", "users", "/api/users"),
        ]
    )
    def test_endpoint_name_maps_to_table_and_path(self, endpoint: str, table_name: str, path: str) -> None:
        resource = get_resource(endpoint, WORKSPACE_ID, should_use_incremental_field=False, incremental_field=None)
        assert resource["table_name"] == table_name
        endpoint_config = resource["endpoint"]
        assert isinstance(endpoint_config, dict)
        assert endpoint_config["path"] == path
        assert resource["primary_key"] == ["id"]

    def test_incremental_field_falls_back_to_first_advertised_option(self) -> None:
        resource = get_resource(
            "Companies", WORKSPACE_ID, should_use_incremental_field=True, incremental_field="not_a_real_field"
        )
        endpoint_config = resource["endpoint"]
        assert isinstance(endpoint_config, dict)
        params = endpoint_config["params"]
        assert isinstance(params, dict)
        where = params["where"]
        assert isinstance(where, dict)
        assert where["cursor_path"] == "updatedAt"  # ty: ignore[invalid-key]

    def test_incremental_convert_omits_workspace_for_users(self) -> None:
        resource = get_resource("Users", WORKSPACE_ID, should_use_incremental_field=True, incremental_field="updatedAt")
        endpoint_config = resource["endpoint"]
        assert isinstance(endpoint_config, dict)
        params = endpoint_config["params"]
        assert isinstance(params, dict)
        where = params["where"]
        assert isinstance(where, dict)
        convert = where["convert"]  # ty: ignore[invalid-key]
        assert convert is not None
        assert json.loads(convert(None)) == {}

    def test_workspaces_endpoint_never_goes_incremental(self) -> None:
        # Workspaces declares no incremental_fields, so should_use_incremental_field=True must
        # still fall through to a plain, full-refresh where filter.
        resource = get_resource("Workspaces", WORKSPACE_ID, should_use_incremental_field=True, incremental_field=None)
        endpoint_config = resource["endpoint"]
        assert isinstance(endpoint_config, dict)
        params = endpoint_config["params"]
        assert isinstance(params, dict)
        assert "where" not in params
        assert resource["write_disposition"] == "replace"


class TestResolveWorkspaceId:
    def test_returns_the_single_workspace_id(self) -> None:
        with scripted_network(always(_make_http_response({"data": [{"id": WORKSPACE_ID}], "total": 1}))):
            assert resolve_workspace_id("api-key") == WORKSPACE_ID

    def test_raises_when_key_has_multiple_workspaces(self) -> None:
        response = _make_http_response(
            {"data": [{"id": WORKSPACE_ID}, {"id": "22222222-2222-2222-2222-222222222222"}], "total": 2}
        )
        with scripted_network(always(response)):
            with pytest.raises(ValueError, match="access to multiple workspaces"):
                resolve_workspace_id("api-key")

    def test_raises_when_key_has_no_workspace(self) -> None:
        with scripted_network(always(_make_http_response({"data": [], "total": 0}))):
            with pytest.raises(ValueError, match="isn't a member of any workspace"):
                resolve_workspace_id("api-key")

    def test_raises_on_http_error(self) -> None:
        with scripted_network(always(_make_http_response(None, status_code=401))):
            with pytest.raises(requests.HTTPError):
                resolve_workspace_id("api-key")


class TestZeroSourceResumeBehavior:
    """End-to-end resume behaviour of ``ZeroSource``, driven through ``source_for_pipeline``."""

    def _drive(
        self,
        endpoint: str,
        responses: list[ScriptedResponse],
        resume_state: ZeroResumeConfig | None = None,
    ) -> DriveResult:
        driver = SourceDriver(ZeroSource(), ZeroSourceConfig(api_key="test-key"))
        workspaces = _make_http_response({"data": [{"id": WORKSPACE_ID}], "total": 1})
        return driver.run(
            endpoint,
            route({"/api/workspaces": [workspaces], "/api/companies": responses}),
            resume_state=resume_state,
        )

    def test_fresh_run_saves_offset_after_each_non_terminal_page(self) -> None:
        # The offset paginator's default limit is 100, so a non-terminal page must carry a full
        # 100 rows — anything smaller would (correctly) be read as the last page and stop pagination.
        responses = [
            _make_http_response({"data": [{"id": f"c{i}"} for i in range(100)], "total": 250}),
            _make_http_response({"data": [{"id": f"c{i}"} for i in range(100, 200)], "total": 250}),
            _make_http_response({"data": [{"id": f"c{i}"} for i in range(200, 250)], "total": 250}),
        ]
        result = self._drive("Companies", responses)

        company_requests = [request for request in result.requests if request.path == "/api/companies"]
        assert [request.param("offset") for request in company_requests] == ["0", "100", "200"]
        assert [row["id"] for row in result.rows] == [f"c{i}" for i in range(250)]
        assert result.saved_states == [ZeroResumeConfig(offset=100), ZeroResumeConfig(offset=200)]

    def test_resume_seeds_paginator_with_saved_offset(self) -> None:
        responses = [_make_http_response({"data": [{"id": "c4"}], "total": 201})]
        result = self._drive("Companies", responses, resume_state=ZeroResumeConfig(offset=200))

        company_requests = [request for request in result.requests if request.path == "/api/companies"]
        assert [request.param("offset") for request in company_requests] == ["200"]
