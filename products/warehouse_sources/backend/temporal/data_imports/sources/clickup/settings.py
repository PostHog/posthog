from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How an endpoint is fetched. Routed on in `clickup.py:get_rows`.
#   "workspaces"      -> GET /team (lists the workspaces the token can access)
#   "team_scoped"     -> GET /team/{workspace_id}/<resource> returning {data_key: [...]}
#   "tasks"           -> GET /team/{workspace_id}/task (page paginated, incremental)
#   "space_children"  -> fan-out: list spaces, then GET /space/{space_id}/<resource>
#   "lists"           -> fan-out: folderless lists per space + lists per folder
EndpointKind = Literal["workspaces", "team_scoped", "tasks", "space_children", "lists"]


@dataclass
class ClickUpEndpointConfig:
    name: str
    kind: EndpointKind
    # Key the array is wrapped under in the JSON response (e.g. {"spaces": [...]}).
    data_key: str
    primary_keys: list[str]
    # Resource path segment for team_scoped / space_children endpoints.
    resource_path: Optional[str] = None
    # Stable (never-changing) datetime field used for datetime partitioning.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)

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
}

ENDPOINTS = tuple(CLICKUP_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CLICKUP_ENDPOINTS.items()
}
