from dataclasses import field
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

DEFAULT_BASE_URL = "https://api.plane.so"
API_PATH = "/api/v2"
# The v2 lists cap a page at 200 rows.
PAGE_SIZE = 200


@frozen
class PlaneEndpointConfig:
    name: str
    path: str
    description: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    params: dict[str, Any] = field(default_factory=dict)
    # Offset pages stop at row 10,000, so a list that can grow past that pages by cursor.
    # Cursor pages need an ordering on the resource's cursor allowlist.
    cursor_paginated: bool = False
    partition_key: str | None = "created_at"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    page_size: int = PAGE_SIZE
    fanout: DependentEndpointConfig | None = None


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# A per-project list inherits the project id, because its rows carry no project_id of their own.
_PROJECT_FANOUT = DependentEndpointConfig(
    parent_name="projects",
    resolve_param="project_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "project_id"},
    parent_params={"include_archived": "true", "order_by": "created_at", "count": "false"},
    child_params={"include_archived": "true", "order_by": "created_at", "count": "false"},
    # A project deleted between the parent page and its child request has nothing left to list.
    child_response_actions=[{"status_code": 404, "action": "ignore"}],
)

ENDPOINTS: dict[str, PlaneEndpointConfig] = {
    "projects": PlaneEndpointConfig(
        name="projects",
        path="/workspaces/{slug}/projects/",
        description="Projects in the workspace, archived ones included.",
        params={"include_archived": "true", "order_by": "created_at", "count": "false"},
    ),
    "work_items": PlaneEndpointConfig(
        name="work_items",
        path="/workspaces/{slug}/work-items/",
        description="Work items (issues) from every project in the workspace, archived ones included.",
        # `archived=true` lifts every default exclusion, drafts included, so drafts are asked out again.
        params={"archived": "true", "is_draft": "false", "paginate": "cursor"},
        cursor_paginated=True,
        incremental_fields=[_datetime_field("updated_at"), _datetime_field("created_at")],
        default_incremental_field="updated_at",
    ),
    "states": PlaneEndpointConfig(
        name="states",
        path="/workspaces/{slug}/states/",
        description="Workflow states of every project, or the workspace catalog when states are managed centrally.",
        params={"order_by": "created_at", "count": "false"},
    ),
    "members": PlaneEndpointConfig(
        name="members",
        path="/workspaces/{slug}/members/",
        description="Workspace memberships with each member's role and profile.",
        params={"expand": "member", "count": "false"},
        partition_key=None,
    ),
    "cycles": PlaneEndpointConfig(
        name="cycles",
        path="/workspaces/{slug}/projects/{project_id}/cycles/",
        description="Time-boxed cycles of every project, archived ones included.",
        fanout=_PROJECT_FANOUT,
    ),
    "modules": PlaneEndpointConfig(
        name="modules",
        path="/workspaces/{slug}/projects/{project_id}/modules/",
        description="Modules of every project, archived ones included.",
        fanout=_PROJECT_FANOUT,
    ),
    "labels": PlaneEndpointConfig(
        name="labels",
        path="/workspaces/{slug}/projects/{project_id}/labels/",
        description="Work item labels of every project.",
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="project_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "project_id"},
            parent_params={"include_archived": "true", "order_by": "created_at", "count": "false"},
            child_params={"order_by": "created_at", "count": "false"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: endpoint.incremental_fields for name, endpoint in ENDPOINTS.items() if endpoint.incremental_fields
}
