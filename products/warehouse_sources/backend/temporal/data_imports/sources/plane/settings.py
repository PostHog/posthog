from dataclasses import field, replace
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


# Every list pages by cursor: offset pages stop at row 10,000. A cursor page needs an ordering on the
# resource's cursor allowlist, and `created_at` and `id` are on every v2 list's allowlist.
_CURSOR = {"paginate": "cursor", "order_by": "created_at"}

# A per-project list inherits the project id, because its rows carry no project_id of their own.
_PROJECT_FANOUT = DependentEndpointConfig(
    parent_name="projects",
    resolve_param="project_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "project_id"},
    parent_params={"include_archived": "true", **_CURSOR},
    child_params={"include_archived": "true", **_CURSOR},
    # A project deleted between the parent page and its child request has nothing left to list.
    child_response_actions=[{"status_code": 404, "action": "ignore"}],
)

# Lists that have no archived records of their own take no archive filter.
_PROJECT_FANOUT_NO_ARCHIVE_FILTER = replace(_PROJECT_FANOUT, child_params=dict(_CURSOR))

ENDPOINTS: dict[str, PlaneEndpointConfig] = {
    "projects": PlaneEndpointConfig(
        name="projects",
        path="/workspaces/{slug}/projects/",
        description="Projects in the workspace, archived ones included.",
        params={"include_archived": "true", **_CURSOR},
    ),
    "work_items": PlaneEndpointConfig(
        name="work_items",
        path="/workspaces/{slug}/work-items/",
        description="Work items (issues) from every project in the workspace, archived ones included.",
        # `archived=true` lifts every default exclusion, drafts included, so drafts are asked out again.
        params={"archived": "true", "is_draft": "false", **_CURSOR},
        incremental_fields=[_datetime_field("updated_at"), _datetime_field("created_at")],
        default_incremental_field="updated_at",
    ),
    "states": PlaneEndpointConfig(
        name="states",
        path="/workspaces/{slug}/projects/{project_id}/states/",
        # Per project: the workspace route leaves out archived projects and every triage state,
        # which work items still point at.
        description="Workflow states of every project, archived projects and triage states included.",
        primary_keys=["project_id", "id"],
        fanout=_PROJECT_FANOUT_NO_ARCHIVE_FILTER,
    ),
    "members": PlaneEndpointConfig(
        name="members",
        path="/workspaces/{slug}/members/",
        description="Workspace memberships with each member's role and profile.",
        # A membership row has no created_at, so it walks by id, the other cursor-eligible ordering.
        params={"expand": "member", "paginate": "cursor", "order_by": "id"},
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
        fanout=_PROJECT_FANOUT_NO_ARCHIVE_FILTER,
    ),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: endpoint.incremental_fields for name, endpoint in ENDPOINTS.items() if endpoint.incremental_fields
}
