from dataclasses import field
from typing import Any, Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Where an endpoint's rows live: directly on the account, under one workspace, one project, or one
# project security scan. Anything but "account" is fanned out over the parents discovered at sync time.
EndpointScope = Literal["account", "workspace", "project", "scan"]

LOVABLE_API_BASE_URL = "https://api.lovable.dev"

# Version segment prefixed onto every endpoint path. Lovable also serves a `/v1beta` channel for
# preview endpoints (audit logs, message exports); this source only calls the GA one.
LOVABLE_API_VERSION_V1 = "v1"
# Dated stable version, selected by the `Lovable-Version` header on the same `/v1` paths.
LOVABLE_API_VERSION_2026_09_11 = "2026-09-11"

LOVABLE_URL_VERSION_SEGMENT = "v1"

# Analytics endpoints reject a date range longer than 365 days.
ANALYTICS_MAX_RANGE_DAYS = 365


@frozen
class LovableEndpointConfig:
    name: str
    path: str
    scope: EndpointScope
    primary_keys: list[str]
    # Query param carrying the parent id, for endpoints that take it that way instead of in the
    # path. Only `/projects` does, which is workspace-scoped via `?workspace_id=`.
    parent_id_param: str | None = None
    partition_key: str | None = None
    page_size: int = 100
    params: dict[str, Any] = field(default_factory=dict)
    # Lowest Lovable plan that may call the endpoint. Below it the API answers 402, so this is the
    # reason surfaced per table in the schema picker rather than a sync that can only ever fail.
    minimum_plan: str | None = None
    # The endpoint returns one unpaginated `time_series` object over a required date range instead
    # of a cursor page of rows.
    time_series: bool = False
    # Lovable answers 404 for an unpublished project, so only published projects are fanned out.
    published_projects_only: bool = False


LOVABLE_ENDPOINTS: dict[str, LovableEndpointConfig] = {
    "Workspaces": LovableEndpointConfig(
        name="Workspaces",
        path="/workspaces",
        scope="account",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "Projects": LovableEndpointConfig(
        name="Projects",
        path="/projects",
        scope="workspace",
        parent_id_param="workspace_id",
        primary_keys=["id"],
        partition_key="created_at",
        # Both filters default to a narrowed set, so a table synced without them would silently
        # miss personal drafts and unpublished projects.
        params={"visibility": "all", "publish_status": "any"},
    ),
    "WorkspaceMembers": LovableEndpointConfig(
        name="WorkspaceMembers",
        path="/workspaces/{workspace_id}/members",
        scope="workspace",
        primary_keys=["workspace_id", "user_id"],
        partition_key="invited_at",
        page_size=50,
        # `status` defaults to "active", which drops every pending invite.
        params={"status": "all"},
        minimum_plan="Enterprise",
    ),
    "WorkspaceCreditHistory": LovableEndpointConfig(
        name="WorkspaceCreditHistory",
        path="/workspaces/{workspace_id}/billing/credit-history",
        scope="workspace",
        primary_keys=["workspace_id", "id"],
        partition_key="occurred_at",
        minimum_plan="Enterprise",
    ),
    "ProjectCollaborators": LovableEndpointConfig(
        name="ProjectCollaborators",
        path="/projects/{project_id}/collaborators",
        scope="project",
        primary_keys=["project_id", "user_id"],
        # `invited_at` is the only timestamp and it is null for the project owner, so there is no
        # stable column to partition on.
        minimum_plan="Enterprise",
    ),
    "ProjectSecurityScans": LovableEndpointConfig(
        name="ProjectSecurityScans",
        path="/projects/{project_id}/security-scans",
        scope="project",
        primary_keys=["project_id", "scan_id"],
        partition_key="started_at",
        minimum_plan="Business",
    ),
    "ProjectPiiLabels": LovableEndpointConfig(
        name="ProjectPiiLabels",
        path="/projects/{project_id}/pii-labels",
        scope="project",
        primary_keys=["project_id", "id"],
        partition_key="found_at",
        minimum_plan="Enterprise",
    ),
}

# 2026-09-11 drops credit history and project collaborators, lists only accepted members, and
# names the scan key `id`. Its project filters already default to every project, so none are sent.
LOVABLE_ENDPOINTS_2026_09_11: dict[str, LovableEndpointConfig] = {
    "Workspaces": LOVABLE_ENDPOINTS["Workspaces"],
    "Projects": LovableEndpointConfig(
        name="Projects",
        path="/projects",
        scope="workspace",
        parent_id_param="workspace_id",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "WorkspaceMembers": LovableEndpointConfig(
        name="WorkspaceMembers",
        path="/workspaces/{workspace_id}/members",
        scope="workspace",
        primary_keys=["workspace_id", "user_id"],
        page_size=50,
        minimum_plan="Business",
    ),
    "ProjectSecurityScans": LovableEndpointConfig(
        name="ProjectSecurityScans",
        path="/projects/{project_id}/security-scans",
        scope="project",
        primary_keys=["project_id", "id"],
        partition_key="started_at",
        minimum_plan="Business",
    ),
    "ProjectPiiLabels": LOVABLE_ENDPOINTS["ProjectPiiLabels"],
    "WorkspaceGroups": LovableEndpointConfig(
        name="WorkspaceGroups",
        path="/workspaces/{workspace_id}/groups",
        scope="workspace",
        primary_keys=["workspace_id", "id"],
        partition_key="created_at",
        minimum_plan="Business",
    ),
    "ProjectSecurityScanFindings": LovableEndpointConfig(
        name="ProjectSecurityScanFindings",
        path="/projects/{project_id}/security-scans/{scan_id}/findings",
        scope="scan",
        # Each scan is a full snapshot that repeats findings carried over from earlier scans under
        # the same finding id, so the scan id is part of the key.
        primary_keys=["project_id", "scan_id", "id"],
        partition_key="created_at",
        minimum_plan="Business",
    ),
    "ProjectAnalytics": LovableEndpointConfig(
        name="ProjectAnalytics",
        path="/projects/{project_id}/analytics",
        scope="project",
        primary_keys=["project_id", "timestamp"],
        partition_key="timestamp",
        minimum_plan="Business",
        time_series=True,
        published_projects_only=True,
    ),
    "WorkspaceAnalytics": LovableEndpointConfig(
        name="WorkspaceAnalytics",
        path="/workspaces/{workspace_id}/analytics",
        scope="workspace",
        primary_keys=["workspace_id", "timestamp"],
        partition_key="timestamp",
        minimum_plan="Business",
        time_series=True,
    ),
}


@frozen
class LovableVersionConfig:
    endpoints: dict[str, LovableEndpointConfig]
    # `Lovable-Version` header value. v1 predates dated versions and sends none.
    version_header: str | None
    # Read by the credential probe. 2026-09-11 has no `/me`.
    probe_path: str


LOVABLE_VERSIONS: dict[str, LovableVersionConfig] = {
    LOVABLE_API_VERSION_V1: LovableVersionConfig(
        endpoints=LOVABLE_ENDPOINTS,
        version_header=None,
        probe_path="/me",
    ),
    LOVABLE_API_VERSION_2026_09_11: LovableVersionConfig(
        endpoints=LOVABLE_ENDPOINTS_2026_09_11,
        version_header=LOVABLE_API_VERSION_2026_09_11,
        probe_path="/workspaces?limit=1",
    ),
}


def version_config(api_version: str) -> LovableVersionConfig:
    try:
        return LOVABLE_VERSIONS[api_version]
    except KeyError as e:
        raise ValueError(f"Unsupported Lovable API version: {api_version!r}") from e


# Every list endpoint paginates by opaque cursor with no timestamp filter, so none of those tables
# can sync incrementally. Only the analytics endpoints take a server-side `starts_at`.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "ProjectAnalytics": [incremental_field("timestamp", IncrementalFieldType.DateTime)],
    "WorkspaceAnalytics": [incremental_field("timestamp", IncrementalFieldType.DateTime)],
}

# An incremental analytics run reads the watermark day again, so append would duplicate that bucket.
MERGE_ONLY_ENDPOINTS = frozenset(INCREMENTAL_FIELDS)
