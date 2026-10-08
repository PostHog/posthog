from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)


@dataclass
class WrikeEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field used for datetime partitioning. Only set where the resource
    # exposes an immutable creation timestamp — never an `updatedDate`-style field, which would
    # rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # Wrike paginates a small number of large list endpoints (`/tasks`, `/comments`,
    # `/audit_log`) via `pageSize` + `nextPageToken`. Most endpoints (folders, contacts,
    # workflows, custom fields, spaces) return the full result set in a single response with no
    # pagination token, so we fetch them in one request.
    paginated: bool = False
    # Set when the path takes a parameter resolved from another endpoint's rows.
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = 1000
    incremental_fields: list[Any] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


# Wrike's REST API (v4) does not expose a server-side cursor/timestamp filter we can reliably
# map onto an incremental watermark without live verification: only a handful of endpoints accept
# an `updatedDate` range and combining it with `nextPageToken` paging and the 1000-row page cap
# has ordering edge cases we can't confirm without credentials. We therefore ship every endpoint
# as full refresh (matching Airbyte's Wrike connector); incremental sync can be layered on later
# once the `updatedDate` filter is curl-verified against the live API.
WRIKE_ENDPOINTS: dict[str, WrikeEndpointConfig] = {
    "tasks": WrikeEndpointConfig(
        name="tasks",
        path="/tasks",
        partition_key="createdDate",
        paginated=True,
    ),
    "folders": WrikeEndpointConfig(
        name="folders",
        path="/folders",
    ),
    "contacts": WrikeEndpointConfig(
        name="contacts",
        path="/contacts",
    ),
    "workflows": WrikeEndpointConfig(
        name="workflows",
        path="/workflows",
    ),
    "custom_fields": WrikeEndpointConfig(
        name="custom_fields",
        path="/customfields",
    ),
    "spaces": WrikeEndpointConfig(
        name="spaces",
        path="/spaces",
    ),
    "project_dependencies": WrikeEndpointConfig(
        name="project_dependencies",
        path="/folders/{folderId}/dependencies",
        # A project-to-project dependency is listed under both its predecessor and successor
        # project, so the dependency id alone repeats across parents.
        primary_keys=["projectId", "id"],
        fanout=DependentEndpointConfig(
            parent_name="folders",
            resolve_param="folderId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "projectId"},
            # The endpoint rejects any folder id that is not a project.
            parent_params={"project": "true"},
            # A project deleted between the parent listing and this fetch 404s.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(WRIKE_ENDPOINTS.keys())
