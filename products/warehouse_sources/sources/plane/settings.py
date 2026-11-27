from dataclasses import field, replace
from typing import Any

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    IncrementalFieldType,
    frozen,
)

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
    # Child path params bound from other fields of the same parent row, keyed by path param.
    parent_path_fields: dict[str, str] = field(default_factory=dict)
    resume_parent_pagination: bool = False


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

# `archived=true` lifts every default exclusion, drafts included, so drafts are asked out again.
_WORK_ITEMS_PARAMS = {"archived": "true", "is_draft": "false", **_CURSOR}

# Comments and activities hang off one work item and have no workspace-wide list. The workspace work
# item list reaches every work item, and its rows carry the project id the child path also needs.
_WORK_ITEM_FANOUT = DependentEndpointConfig(
    parent_name="work_items",
    resolve_param="work_item_id",
    resolve_field="id",
    include_from_parent=["project_id"],
    parent_field_renames={"project_id": "project_id"},
    parent_params={**_WORK_ITEMS_PARAMS, "fields": "id,project_id"},
    child_params=dict(_CURSOR),
    # A work item deleted between the parent page and its child request has nothing left to list.
    child_response_actions=[{"status_code": 404, "action": "ignore"}],
)

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
        params=dict(_WORK_ITEMS_PARAMS),
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
    "estimates": PlaneEndpointConfig(
        name="estimates",
        path="/workspaces/{slug}/projects/{project_id}/estimates/",
        description="Estimate scales of every project, with their points.",
        primary_keys=["project_id", "id"],
        fanout=replace(_PROJECT_FANOUT_NO_ARCHIVE_FILTER, child_params={"expand": "points", **_CURSOR}),
    ),
    "work_item_types": PlaneEndpointConfig(
        name="work_item_types",
        path="/workspaces/{slug}/projects/{project_id}/work-item-types/",
        description="Work item types of every project.",
        # A type shared from the workspace is listed once in each project it is added to.
        primary_keys=["project_id", "id"],
        fanout=_PROJECT_FANOUT_NO_ARCHIVE_FILTER,
    ),
    # Full refresh only: the fan-out sends one request per work item either way, and a watermark taken
    # across work items skips rows written to an earlier work item while the run is still going.
    "work_item_comments": PlaneEndpointConfig(
        name="work_item_comments",
        path="/workspaces/{slug}/projects/{project_id}/work-items/{work_item_id}/comments/",
        description="Comments on every work item, replies included as their own rows.",
        primary_keys=["work_item_id", "id"],
        fanout=_WORK_ITEM_FANOUT,
        parent_path_fields={"project_id": "project_id"},
        resume_parent_pagination=True,
    ),
    "work_item_activities": PlaneEndpointConfig(
        name="work_item_activities",
        path="/workspaces/{slug}/projects/{project_id}/work-items/{work_item_id}/activities/",
        description="Change history of every work item: one row per recorded field change or action.",
        primary_keys=["work_item_id", "id"],
        fanout=_WORK_ITEM_FANOUT,
        parent_path_fields={"project_id": "project_id"},
        resume_parent_pagination=True,
    ),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: endpoint.incremental_fields for name, endpoint in ENDPOINTS.items() if endpoint.incremental_fields
}
