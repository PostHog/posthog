from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How an endpoint is fetched. Routed on in `clickup.py:clickup_source`.
#   "workspaces"          -> GET /team (lists the workspaces the token can access)
#   "team_scoped"         -> GET /team/{workspace_id}/<resource> returning {data_key: [...]}
#   "tasks"               -> GET /team/{workspace_id}/task (page paginated, incremental)
#   "space_children"      -> fan-out: list spaces, then GET /space/{space_id}/<resource>
#   "lists"               -> fan-out: folderless lists per space + lists per folder
#   "list_children"       -> fan-out: every list, then GET /list/{list_id}/<resource>
#   "time_entries"        -> GET /team/{workspace_id}/time_entries walked in date windows
#   "task_time_in_status" -> fan-out: every task id, then the bulk time-in-status endpoint
EndpointKind = Literal[
    "workspaces",
    "team_scoped",
    "tasks",
    "space_children",
    "lists",
    "list_children",
    "time_entries",
    "task_time_in_status",
]


@dataclass(frozen=True)
class ClickUpEndpointConfig:
    name: str
    kind: EndpointKind
    primary_keys: list[str]
    # Key the array is wrapped under in the JSON response (e.g. {"spaces": [...]}). None when the
    # response is not a wrapped array. The bulk time-in-status endpoint answers with a map keyed
    # by task id, which `clickup.py` reshapes itself.
    data_key: Optional[str] = None
    # Resource path segment for team_scoped / space_children / list_children endpoints.
    resource_path: Optional[str] = None
    # Stable (never-changing) datetime field used for datetime partitioning.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Whether the schema picker pre-selects this table. The task and list fan-outs cost one request
    # per parent on every sync, so they are opt-in rather than on by default.
    should_sync_default: bool = True

    @property
    def supports_incremental(self) -> bool:
        return len(self.incremental_fields) > 0


CLICKUP_ENDPOINTS: dict[str, ClickUpEndpointConfig] = {
    "workspaces": ClickUpEndpointConfig(
        name="workspaces",
        kind="workspaces",
        data_key="teams",
        primary_keys=["id"],
    ),
    "spaces": ClickUpEndpointConfig(
        name="spaces",
        kind="team_scoped",
        resource_path="space",
        data_key="spaces",
        primary_keys=["id"],
    ),
    "folders": ClickUpEndpointConfig(
        name="folders",
        kind="space_children",
        resource_path="folder",
        data_key="folders",
        primary_keys=["id"],
    ),
    "lists": ClickUpEndpointConfig(
        name="lists",
        kind="lists",
        data_key="lists",
        primary_keys=["id"],
    ),
    "tasks": ClickUpEndpointConfig(
        name="tasks",
        kind="tasks",
        data_key="tasks",
        primary_keys=["id"],
        partition_key="date_created",
        incremental_fields=[
            {
                "label": "date_updated",
                "type": IncrementalFieldType.DateTime,
                "field": "date_updated",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "goals": ClickUpEndpointConfig(
        name="goals",
        kind="team_scoped",
        resource_path="goal",
        data_key="goals",
        primary_keys=["id"],
    ),
    "time_entries": ClickUpEndpointConfig(
        name="time_entries",
        kind="time_entries",
        data_key="data",
        primary_keys=["id"],
        # `start` is the only timestamp ClickUp's date-range filter bounds, so it is the only field
        # an incremental sync can advance on. No partitioning: a tracked entry's start can be
        # edited after the fact, which would move the row's partition and orphan the original.
        incremental_fields=[
            {
                "label": "start",
                "type": IncrementalFieldType.DateTime,
                "field": "start",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "task_time_in_status": ClickUpEndpointConfig(
        name="task_time_in_status",
        kind="task_time_in_status",
        primary_keys=["task_id"],
        should_sync_default=False,
    ),
    "custom_fields": ClickUpEndpointConfig(
        name="custom_fields",
        kind="team_scoped",
        resource_path="field",
        data_key="fields",
        primary_keys=["id"],
    ),
    "list_custom_fields": ClickUpEndpointConfig(
        name="list_custom_fields",
        kind="list_children",
        resource_path="field",
        data_key="fields",
        # One row per (list, field): a field defined above the list is accessible to every list
        # under it, so the field id alone repeats across the table.
        primary_keys=["_list_id", "id"],
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(CLICKUP_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CLICKUP_ENDPOINTS.items()
}

SHOULD_SYNC_DEFAULTS: dict[str, bool] = {name: config.should_sync_default for name, config in CLICKUP_ENDPOINTS.items()}
