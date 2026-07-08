from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class ClockifyEndpointConfig:
    name: str
    # Path template relative to the API base. Placeholders are filled per fan-out scope:
    # {workspace_id} for every workspace-scoped endpoint, plus {project_id}/{user_id} for the
    # two-level fan-out endpoints (tasks/time_entries).
    path: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Stable creation-style field used to partition the Delta table. Never an `updated_at`
    # style field — those rewrite partitions on every sync.
    partition_key: Optional[str] = None
    sort_mode: Literal["asc", "desc"] = "asc"
    # Clockify's max page-size is 5000; 1000 keeps each page well under the response/memory
    # ceiling while minimizing request count.
    page_size: int = 1000
    should_sync_default: bool = True
    # False only for `/workspaces`, which is the top-level enumeration every other endpoint
    # fans out over. All other endpoints require a `{workspace_id}` in their path.
    workspace_scoped: bool = True
    # For two-level fan-out: the name of the parent endpoint whose ids seed this child's path
    # (e.g. tasks fan out over `projects`, time_entries over `users`).
    fan_out_parent: Optional[str] = None
    # The path placeholder filled with each parent id during a two-level fan-out.
    parent_id_placeholder: Optional[str] = None
    # Query param name for the server-side timestamp filter, when the endpoint exposes one.
    # Only time-entries does (`start` filters entries that started after the given datetime).
    incremental_param: Optional[str] = None


_TIME_ENTRY_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "time_interval_start",
        "type": IncrementalFieldType.DateTime,
        "field": "time_interval_start",
        "field_type": IncrementalFieldType.DateTime,
    },
]


CLOCKIFY_ENDPOINTS: dict[str, ClockifyEndpointConfig] = {
    # Top-level: the workspaces the API key's user belongs to. Every other endpoint fans out
    # over these ids. Workspaces are few per user and the endpoint is not paginated.
    "workspaces": ClockifyEndpointConfig(
        name="workspaces",
        path="/workspaces",
        primary_keys=["id"],
        workspace_scoped=False,
    ),
    "users": ClockifyEndpointConfig(
        name="users",
        path="/workspaces/{workspace_id}/users",
        primary_keys=["workspace_id", "id"],
    ),
    "clients": ClockifyEndpointConfig(
        name="clients",
        path="/workspaces/{workspace_id}/clients",
        primary_keys=["workspace_id", "id"],
    ),
    "projects": ClockifyEndpointConfig(
        name="projects",
        path="/workspaces/{workspace_id}/projects",
        primary_keys=["workspace_id", "id"],
    ),
    "tags": ClockifyEndpointConfig(
        name="tags",
        path="/workspaces/{workspace_id}/tags",
        primary_keys=["workspace_id", "id"],
    ),
    # Two-level fan-out: workspace -> project -> tasks. The task id is unique per project, so
    # the parent ids are part of the primary key to stay unique table-wide.
    "tasks": ClockifyEndpointConfig(
        name="tasks",
        path="/workspaces/{workspace_id}/projects/{project_id}/tasks",
        primary_keys=["workspace_id", "project_id", "id"],
        fan_out_parent="projects",
        parent_id_placeholder="project_id",
    ),
    # Two-level fan-out: workspace -> user -> time-entries. The only endpoint with a genuine
    # server-side time filter (`start`), so the only one that supports incremental sync.
    # Clockify returns time entries newest-first by start time and exposes no sort param, so
    # sort_mode is "desc"; the watermark is the (flattened) interval start.
    "time_entries": ClockifyEndpointConfig(
        name="time_entries",
        path="/workspaces/{workspace_id}/user/{user_id}/time-entries",
        primary_keys=["workspace_id", "user_id", "id"],
        incremental_fields=_TIME_ENTRY_INCREMENTAL_FIELDS,
        default_incremental_field="time_interval_start",
        partition_key="time_interval_start",
        sort_mode="desc",
        fan_out_parent="users",
        parent_id_placeholder="user_id",
        incremental_param="start",
    ),
}

ENDPOINTS = tuple(CLOCKIFY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CLOCKIFY_ENDPOINTS.items()
}
