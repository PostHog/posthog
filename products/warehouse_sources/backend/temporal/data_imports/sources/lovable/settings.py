from dataclasses import field
from typing import Any, Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

# Where an endpoint's rows live: directly on the account, under one workspace, or under one
# project. Anything but "account" is fanned out over the parents discovered at sync time.
EndpointScope = Literal["account", "workspace", "project"]

LOVABLE_API_BASE_URL = "https://api.lovable.dev"

# Version segment prefixed onto every endpoint path. Lovable also serves a `/v1beta` channel for
# preview endpoints (audit logs, message exports); this source only calls the GA one.
LOVABLE_API_VERSION_V1 = "v1"


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

ENDPOINTS = tuple(LOVABLE_ENDPOINTS.keys())

# Every v1 list endpoint paginates by opaque cursor with no timestamp filter, so none of these
# tables can sync incrementally. A run either walks the collection or it skips rows.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
