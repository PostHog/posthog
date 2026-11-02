from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# n8n's public REST API is served per-instance under this base path.
N8N_API_PATH = "/api/v1"

# Cursor pagination page size. The API defaults to 100 and caps at 250; we
# request the max to minimize round trips on large instances.
PAGE_SIZE = 250

# n8n caps how far back insights reach per license plan and answers 403 beyond that.
# A backfill tries the longest window first and steps down until the instance accepts one.
INSIGHTS_BACKFILL_DAYS = (365, 90, 30, 7)


@dataclass(frozen=True)
class N8nEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable datetime field used for datetime partitioning. n8n objects that
    # carry no timestamp (variables, projects) leave this None and go unpartitioned.
    partition_key: Optional[str] = None
    # Extra query params sent on every list request for this endpoint.
    extra_params: dict[str, str] = field(default_factory=dict)
    # Folders page with skip/take and a total `count`; every other list endpoint uses a cursor.
    paginator: Literal["cursor", "offset"] = "cursor"
    page_size: int = PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Set on endpoints whose path needs an id from a parent endpoint's rows. A parent that
    # itself fans out makes a two-level chain.
    fanout: Optional[DependentEndpointConfig] = None


# A parent row deleted between its listing and the child fetch 404s; skip it instead of failing.
_IGNORE_404: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]


N8N_ENDPOINTS: dict[str, N8nEndpointConfig] = {
    # Workflows carry createdAt/updatedAt. `excludePinnedData` keeps the
    # dev-time pinned sample payloads out of each row.
    "workflows": N8nEndpointConfig(
        name="workflows",
        path="/workflows",
        partition_key="createdAt",
        extra_params={"excludePinnedData": "true"},
    ),
    # Executions have no createdAt/updatedAt; startedAt is the stable creation
    # timestamp. The heavy per-run `data` blob is omitted (includeData defaults
    # to false) to keep rows small.
    "executions": N8nEndpointConfig(
        name="executions",
        path="/executions",
        partition_key="startedAt",
    ),
    "tags": N8nEndpointConfig(
        name="tags",
        path="/tags",
        partition_key="createdAt",
    ),
    "users": N8nEndpointConfig(
        name="users",
        path="/users",
        partition_key="createdAt",
    ),
    # Variables and projects expose no timestamp field, so they are full refresh
    # only with no datetime partitioning.
    "variables": N8nEndpointConfig(
        name="variables",
        path="/variables",
    ),
    "projects": N8nEndpointConfig(
        name="projects",
        path="/projects",
    ),
    "project_users": N8nEndpointConfig(
        name="project_users",
        path="/projects/{projectId}/users",
        primary_keys=["projectId", "id"],
        partition_key="createdAt",
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="projectId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "projectId"},
            child_response_actions=_IGNORE_404,
        ),
    ),
    # The default sort is updatedAt desc, which shifts offset pages when a folder changes
    # mid-sync, so sort on the immutable createdAt instead.
    "folders": N8nEndpointConfig(
        name="folders",
        path="/projects/{projectId}/folders",
        primary_keys=["projectId", "id"],
        partition_key="createdAt",
        extra_params={"sortBy": "createdAt:asc"},
        paginator="offset",
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="projectId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "projectId"},
            child_response_actions=_IGNORE_404,
        ),
    ),
    "test_runs": N8nEndpointConfig(
        name="test_runs",
        path="/workflows/{workflowId}/test-runs",
        primary_keys=["workflowId", "id"],
        partition_key="createdAt",
        fanout=DependentEndpointConfig(
            parent_name="workflows",
            resolve_param="workflowId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "workflowId"},
            child_response_actions=_IGNORE_404,
        ),
    ),
    # Test cases carry no createdAt, so they go unpartitioned.
    "test_cases": N8nEndpointConfig(
        name="test_cases",
        path="/workflows/{workflowId}/test-runs/{runId}/test-cases",
        primary_keys=["testRunId", "id"],
        fanout=DependentEndpointConfig(
            parent_name="test_runs",
            resolve_param="runId",
            resolve_field="id",
            include_from_parent=["id", "_workflows_id"],
            parent_field_renames={"id": "testRunId", "_workflows_id": "workflowId"},
            child_response_actions=_IGNORE_404,
        ),
    ),
    # The summary endpoint returns one aggregate object for a date range. We request one UTC
    # day per call so the table holds one row per day, and the startDate/endDate filter makes
    # incremental syncs fetch only the days since the last run.
    "insights_summary": N8nEndpointConfig(
        name="insights_summary",
        path="/insights/summary",
        primary_keys=["date"],
        partition_key="startDate",
        incremental_fields=[incremental_field("startDate")],
        default_incremental_field="startDate",
    ),
}

ENDPOINTS = tuple(N8N_ENDPOINTS.keys())
