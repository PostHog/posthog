from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField

# How a list endpoint pages through results:
# - "offset": `limit`/`offset` params with an `{"objects": [...], "offset", "limit", "totalCount"}` envelope
# - "marker": `limit`/`after` params, with `nextMarker`/`previousMarker` in the response envelope
#   (rows sit under `data` or `objects` depending on the endpoint)
# - "none": the endpoint returns the full collection as a plain JSON array in one response
PaginationStyle = Literal["offset", "marker", "none"]


@dataclass
class SplitIoEndpointConfig:
    name: str
    # Path under the API root. A ``{workspace_id}`` placeholder marks a fan-out endpoint
    # that must be queried once per workspace.
    path: str
    primary_keys: list[str]
    pagination: PaginationStyle = "offset"
    # Envelope key holding the rows (None for plain-array responses).
    data_key: str | None = "objects"
    # Fan-out endpoints depend on the list of workspaces; we inject ``_workspace_id`` into
    # every row so a single table stays meaningful (and uniquely keyed) across workspaces.
    requires_workspace: bool = False
    # Some fan-out endpoints take the workspace as a query param instead of a path segment.
    workspace_query_param: str | None = None
    # Extra query params required by the endpoint.
    extra_params: dict[str, str] = field(default_factory=dict)
    # Most endpoints live under /internal/api/v2; flag sets are served from v3.
    api_version: str = "v2"


# Split (Harness FME) Admin API v2 endpoints. All are full-refresh only: the Admin API exposes
# no server-side timestamp filter (`since`/`updated_after`) on any of these resources — its
# timestamps are epoch-millisecond integers with no range query params — so there is no
# reliable incremental cursor to advance.
SPLIT_IO_ENDPOINTS: dict[str, SplitIoEndpointConfig] = {
    "workspaces": SplitIoEndpointConfig(
        name="workspaces",
        path="/workspaces",
        primary_keys=["id"],
    ),
    "environments": SplitIoEndpointConfig(
        name="environments",
        path="/environments/ws/{workspace_id}",
        primary_keys=["id"],
        pagination="none",
        data_key=None,
        requires_workspace=True,
    ),
    "traffic_types": SplitIoEndpointConfig(
        name="traffic_types",
        path="/trafficTypes/ws/{workspace_id}",
        primary_keys=["id"],
        pagination="none",
        data_key=None,
        requires_workspace=True,
    ),
    "feature_flags": SplitIoEndpointConfig(
        name="feature_flags",
        path="/splits/ws/{workspace_id}",
        # Flag names are unique only within a workspace, so the composite key includes the
        # injected ``_workspace_id``.
        primary_keys=["name", "_workspace_id"],
        requires_workspace=True,
    ),
    "segments": SplitIoEndpointConfig(
        name="segments",
        path="/segments/ws/{workspace_id}",
        # Segment list objects carry no id — they are keyed by name within a workspace.
        primary_keys=["name", "_workspace_id"],
        requires_workspace=True,
    ),
    "rollout_statuses": SplitIoEndpointConfig(
        name="rollout_statuses",
        path="/rolloutStatuses",
        primary_keys=["id"],
        pagination="none",
        data_key=None,
        requires_workspace=True,
        workspace_query_param="wsId",
    ),
    "flag_sets": SplitIoEndpointConfig(
        name="flag_sets",
        path="/flag-sets",
        primary_keys=["id"],
        pagination="marker",
        data_key="data",
        requires_workspace=True,
        workspace_query_param="workspace_id",
        api_version="v3",
    ),
    "groups": SplitIoEndpointConfig(
        name="groups",
        path="/groups",
        primary_keys=["id"],
        pagination="marker",
    ),
    "users": SplitIoEndpointConfig(
        name="users",
        path="/users",
        primary_keys=["id"],
        pagination="marker",
        data_key="data",
    ),
    "change_requests": SplitIoEndpointConfig(
        name="change_requests",
        path="/changeRequests",
        primary_keys=["id"],
        pagination="marker",
        data_key="data",
    ),
}

ENDPOINTS = tuple(SPLIT_IO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
