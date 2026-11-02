from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
import time_machine
from unittest.mock import MagicMock

import orjson
from requests.exceptions import HTTPError
from requests_mock import Mocker

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sim import SimSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sim.sim import (
    AUTH_ERROR,
    PERMISSION_ERROR,
    USAGE_PERMISSION_ERROR,
    USAGE_PROBE_ORGANIZATIONS,
    WORKSPACE_ERROR,
    SimResumeConfig,
    sim_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sim.source import SimSource


@pytest.mark.parametrize("table,key", [("logs", "runId"), ("workflows", "id")])
def test_resume_preserves_workspace_and_sort(
    config: SimSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SimResumeConfig],
    redis_client: MagicMock,
    http: Mocker,
    table: str,
    key: str,
) -> None:
    inputs.schema_name = table
    redis_client.exists.return_value = 1
    redis_client.get.return_value = b'{"cursor":"saved-cursor"}'
    http.get(f"https://www.sim.ai/api/v2/{table}", json={"data": [{key: "remaining-row"}], "nextCursor": None})
    response = sim_source(config, inputs, manager, "v2")
    assert list(cast(Iterable[Any], response.items())) == [[{key: "remaining-row"}]]
    assert http.last_request is not None
    assert http.last_request.qs["cursor"] == ["saved-cursor"]
    assert http.last_request.qs["workspaceid"] == ["workspace-example"]
    assert http.last_request.qs["sortorder"] == ["asc"]


def test_empty_page_keeps_following_cursor(
    config: SimSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SimResumeConfig],
    http: Mocker,
) -> None:
    http.get(
        "https://www.sim.ai/api/v2/logs",
        [
            {"json": {"data": [], "nextCursor": "next-page"}},
            {"json": {"data": [{"runId": "after-empty-page"}], "nextCursor": None}},
        ],
    )
    assert list(cast(Iterable[Any], sim_source(config, inputs, manager, "v2").items())) == [
        [{"runId": "after-empty-page"}]
    ]


def test_missing_data_fails_instead_of_replacing_table_with_empty_rows(
    config: SimSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SimResumeConfig],
    http: Mocker,
) -> None:
    http.get("https://www.sim.ai/api/v2/logs", json={"error": {"code": "UNEXPECTED_RESPONSE"}})
    with pytest.raises(ValueError, match="Required data_selector"):
        list(cast(Iterable[Any], sim_source(config, inputs, manager, "v2").items()))


@pytest.mark.parametrize("status,message", [(401, AUTH_ERROR), (403, PERMISSION_ERROR), (404, WORKSPACE_ERROR)])
def test_auth_failures_are_terminal(
    config: SimSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SimResumeConfig],
    http: Mocker,
    status: int,
    message: str,
) -> None:
    http.get(
        "https://www.sim.ai/api/v2/logs",
        status_code=status,
        json={"error": {"code": "UNAUTHORIZED", "message": "Authentication required"}},
    )
    with pytest.raises(HTTPError) as error:
        list(cast(Iterable[Any], sim_source(config, inputs, manager, "v2").items()))
    assert http.call_count == 1
    messages = SimSource().get_non_retryable_errors()
    assert error_message_matches(str(error.value), messages)
    assert next(value for pattern, value in messages.items() if pattern in str(error.value)) == message


@pytest.mark.parametrize(
    "status,schema,probe_path,expected",
    [
        (200, None, "workflows", (True, None)),
        (200, "logs", "logs", (True, None)),
        (401, None, "workflows", (False, AUTH_ERROR)),
        (403, None, "workflows", (True, None)),
        (403, "logs", "logs", (False, PERMISSION_ERROR)),
        (404, None, "workflows", (False, WORKSPACE_ERROR)),
        (200, "workflow_versions", "workflows", (True, None)),
        (403, "table_rows", "tables", (False, PERMISSION_ERROR)),
        (200, "workspaces", "workspaces", (True, None)),
        (403, "usage_events", "organizations", (False, USAGE_PERMISSION_ERROR)),
    ],
)
def test_credential_probe_maps_status_and_scopes(
    config: SimSourceConfig,
    http: Mocker,
    status: int,
    schema: str | None,
    probe_path: str,
    expected: tuple[bool, str | None],
) -> None:
    http.get(f"https://www.sim.ai/api/v2/{probe_path}", status_code=status, json={"data": [], "nextCursor": None})
    assert validate_credentials(config, "v2", schema) == expected
    assert http.call_count == 1
    assert http.last_request is not None
    assert http.last_request.qs["limit"] == [str(USAGE_PROBE_ORGANIZATIONS) if schema == "usage_events" else "1"]
    assert http.last_request.qs.get("workspaceid") == (
        None if probe_path in ("workspaces", "organizations") else [config.workspace_id]
    )
    assert http.last_request.headers["X-API-Key"] == config.api_key


@pytest.mark.parametrize(
    "usage_statuses,organizations,expected",
    [
        ([403, 403], ["org-a", "org-b"], (False, USAGE_PERMISSION_ERROR)),
        ([403, 200], ["org-a", "org-b"], (True, None)),
        ([200], ["org-a"], (True, None)),
        ([], [], (True, None)),
    ],
)
def test_usage_probe_requires_admin_access_in_one_organization(
    config: SimSourceConfig,
    http: Mocker,
    usage_statuses: list[int],
    organizations: list[str],
    expected: tuple[bool, str | None],
) -> None:
    http.get(
        "https://www.sim.ai/api/v2/organizations",
        json={"data": [{"id": organization} for organization in organizations], "nextCursor": None},
    )
    for organization, status in zip(organizations, usage_statuses, strict=True):
        http.get(
            f"https://www.sim.ai/api/v2/organizations/{organization}/usage/events",
            status_code=status,
            json={"data": [], "nextCursor": None},
        )
    assert validate_credentials(config, "v2", "usage_events") == expected


def test_usage_probe_searches_every_organization_page(config: SimSourceConfig, http: Mocker) -> None:
    http.get(
        "https://www.sim.ai/api/v2/organizations",
        [
            {"json": {"data": [{"id": "org-a"}], "nextCursor": "page-2"}},
            {"json": {"data": [{"id": "org-b"}], "nextCursor": None}},
        ],
    )
    http.get("https://www.sim.ai/api/v2/organizations/org-a/usage/events", status_code=403, json={})
    http.get("https://www.sim.ai/api/v2/organizations/org-b/usage/events", json={"data": [], "nextCursor": None})
    assert validate_credentials(config, "v2", "usage_events") == (True, None)


def test_usage_events_is_merge_only(config: SimSourceConfig) -> None:
    schemas = {schema.name: schema for schema in SimSource().get_schemas(config, 1)}
    assert schemas["usage_events"].supports_incremental
    assert not schemas["usage_events"].supports_append


def test_invalid_request_is_not_reported_as_invalid_credentials(config: SimSourceConfig, http: Mocker) -> None:
    http.get(
        "https://www.sim.ai/api/v2/workflows",
        status_code=400,
        json={"error": {"code": "BAD_REQUEST", "message": "Invalid request"}},
    )
    with pytest.raises(HTTPError):
        validate_credentials(config, "v2")


@pytest.mark.parametrize(
    "table,expected_qs",
    [
        ("workspaces", {"limit": ["100"], "sortby": ["createdat"], "sortorder": ["asc"]}),
        (
            "tables",
            {"limit": ["100"], "sortby": ["createdat"], "sortorder": ["asc"], "workspaceid": ["workspace-example"]},
        ),
    ],
)
def test_top_level_tables_send_only_supported_filters(
    config: SimSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SimResumeConfig],
    http: Mocker,
    table: str,
    expected_qs: dict[str, list[str]],
) -> None:
    inputs.schema_name = table
    http.get(f"https://www.sim.ai/api/v2/{table}", json={"data": [{"id": "row-1"}], "nextCursor": None})
    assert list(cast(Iterable[Any], sim_source(config, inputs, manager, "v2").items())) == [[{"id": "row-1"}]]
    assert http.last_request is not None
    assert http.last_request.qs == expected_qs


@pytest.mark.parametrize(
    "table,parent,child_path,parent_key,child_qs",
    [
        ("workflow_versions", "workflows", "workflows/{}/versions", "workflowId", {"limit": ["100"]}),
        (
            "table_rows",
            "tables",
            "tables/{}/rows",
            "tableId",
            {"limit": ["1000"], "workspaceid": ["workspace-example"]},
        ),
    ],
)
def test_fan_out_walks_child_pages_and_skips_deleted_parents(
    config: SimSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SimResumeConfig],
    http: Mocker,
    table: str,
    parent: str,
    child_path: str,
    parent_key: str,
    child_qs: dict[str, list[str]],
) -> None:
    inputs.schema_name = table
    http.get(
        f"https://www.sim.ai/api/v2/{parent}",
        [
            {"json": {"data": [{"id": "parent-a"}], "nextCursor": "parent-page-2"}},
            {"json": {"data": [{"id": "parent-deleted"}, {"id": "parent-b"}], "nextCursor": None}},
        ],
    )
    http.get(
        f"https://www.sim.ai/api/v2/{child_path.format('parent-a')}",
        [
            {"json": {"data": [{"id": "shared-id"}], "nextCursor": "child-page-2"}},
            {"json": {"data": [{"id": "a-2"}], "nextCursor": None}},
        ],
    )
    http.get(
        f"https://www.sim.ai/api/v2/{child_path.format('parent-deleted')}",
        status_code=404,
        json={"error": {"code": "NOT_FOUND", "message": "Not found"}},
    )
    http.get(
        f"https://www.sim.ai/api/v2/{child_path.format('parent-b')}",
        json={"data": [{"id": "shared-id"}], "nextCursor": None},
    )
    response = sim_source(config, inputs, manager, "v2")
    rows = [row for page in cast(Iterable[Any], response.items()) for row in page]
    assert [(row[parent_key], row["id"]) for row in rows] == [
        ("parent-a", "shared-id"),
        ("parent-a", "a-2"),
        ("parent-b", "shared-id"),
    ]
    assert response.primary_keys == [parent_key, "id"]
    parent_requests = [r for r in http.request_history if r.path == f"/api/v2/{parent}"]
    assert parent_requests[0].qs["workspaceid"] == ["workspace-example"]
    child_request = next(r for r in http.request_history if r.path == f"/api/v2/{child_path.format('parent-b')}")
    assert child_request.qs == child_qs


@pytest.mark.parametrize(
    "should_use_incremental,last_value,expected_start",
    [
        (False, None, "2026-07-17"),
        (False, "2026-10-01T08:00:00Z", "2026-07-17"),
        (True, None, "2026-07-17"),
        (True, "2026-10-01T08:00:00Z", "2026-10-01"),
        (True, datetime(2026, 10, 3, 23, 59, tzinfo=UTC), "2026-10-03"),
        (True, "2026-01-01T00:00:00Z", "2026-07-17"),
        (True, "2026-11-01T00:00:00Z", "2026-10-15"),
    ],
)
def test_usage_events_window_stays_within_vendor_limit(
    config: SimSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SimResumeConfig],
    http: Mocker,
    should_use_incremental: bool,
    last_value: Any,
    expected_start: str,
) -> None:
    inputs.schema_name = "usage_events"
    inputs.should_use_incremental_field = should_use_incremental
    inputs.db_incremental_field_last_value = last_value
    http.get("https://www.sim.ai/api/v2/organizations", json={"data": [{"id": "org-1"}], "nextCursor": None})
    http.get(
        "https://www.sim.ai/api/v2/organizations/org-1/usage/events",
        json={"data": [{"id": "event-1", "createdAt": "2026-10-14T09:00:00Z"}], "nextCursor": None},
    )
    with time_machine.travel(datetime(2026, 10, 15, 12, tzinfo=UTC), tick=False):
        response = sim_source(config, inputs, manager, "v2")
    rows = [row for page in cast(Iterable[Any], response.items()) for row in page]
    assert rows == [{"id": "event-1", "createdAt": "2026-10-14T09:00:00Z", "organizationId": "org-1"}]
    assert http.last_request is not None
    assert http.last_request.qs == {
        "limit": ["100"],
        "preset": ["custom"],
        "startdate": [expected_start],
        "enddate": ["2026-10-15"],
        "sortby": ["createdat"],
        "sortorder": ["asc"],
    }
    organizations_request = http.request_history[0]
    assert "workspaceid" not in organizations_request.qs


def test_usage_events_skip_organizations_without_admin_access(
    config: SimSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SimResumeConfig],
    http: Mocker,
) -> None:
    inputs.schema_name = "usage_events"
    http.get(
        "https://www.sim.ai/api/v2/organizations",
        json={"data": [{"id": "org-member"}, {"id": "org-admin"}], "nextCursor": None},
    )
    http.get(
        "https://www.sim.ai/api/v2/organizations/org-member/usage/events",
        status_code=403,
        json={"error": {"code": "FORBIDDEN", "message": "Organization admin access required"}},
    )
    http.get(
        "https://www.sim.ai/api/v2/organizations/org-admin/usage/events",
        json={"data": [{"id": "event-1"}], "nextCursor": None},
    )
    rows = [row for page in cast(Iterable[Any], sim_source(config, inputs, manager, "v2").items()) for row in page]
    assert rows == [{"id": "event-1", "organizationId": "org-admin"}]


def test_usage_events_resume_reuses_saved_window_and_child_cursor(
    config: SimSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SimResumeConfig],
    redis_client: MagicMock,
    http: Mocker,
) -> None:
    inputs.schema_name = "usage_events"
    redis_client.exists.return_value = 1
    redis_client.get.return_value = orjson.dumps(
        {
            "fanout_state": {
                "completed": ["organizations/org-done/usage/events"],
                "current": "organizations/org-2/usage/events",
                "child_state": {"cursor": "saved-cursor"},
            },
            "start_date": "2026-07-01",
            "end_date": "2026-09-28",
        }
    )
    http.get(
        "https://www.sim.ai/api/v2/organizations",
        json={"data": [{"id": "org-done"}, {"id": "org-2"}], "nextCursor": None},
    )
    http.get(
        "https://www.sim.ai/api/v2/organizations/org-2/usage/events",
        json={"data": [{"id": "event-2"}], "nextCursor": None},
    )
    with time_machine.travel(datetime(2026, 10, 15, 12, tzinfo=UTC), tick=False):
        response = sim_source(config, inputs, manager, "v2")
    rows = [row for page in cast(Iterable[Any], response.items()) for row in page]
    assert rows == [{"id": "event-2", "organizationId": "org-2"}]
    assert http.last_request is not None
    assert http.last_request.qs["cursor"] == ["saved-cursor"]
    assert http.last_request.qs["startdate"] == ["2026-07-01"]
    assert http.last_request.qs["enddate"] == ["2026-09-28"]
    assert all("org-done" not in request.path for request in http.request_history)
