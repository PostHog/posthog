from dataclasses import field
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField


@frozen
class MotionParentConfig:
    name: str
    # Placeholder in the child path that takes the `id` of each parent row.
    resolve_param: str
    # Column that receives the parent `id`, for child rows that do not carry it themselves.
    parent_id_column: Optional[str] = None


@frozen
class MotionEndpointConfig:
    name: str
    path: str
    # Key the rows sit under in the response envelope, alongside `meta`. None for a bare array.
    data_key: Optional[str]
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Extra query params sent on every page.
    params: dict[str, Any] = field(default_factory=dict)
    partition_key: Optional[str] = None
    paginated: bool = True
    parent: Optional[MotionParentConfig] = None


MOTION_ENDPOINTS: dict[str, MotionEndpointConfig] = {
    "workspaces": MotionEndpointConfig(
        name="workspaces",
        path="/v1/workspaces",
        data_key="workspaces",
    ),
    "users": MotionEndpointConfig(
        name="users",
        path="/v1/users",
        data_key="users",
    ),
    "projects": MotionEndpointConfig(
        name="projects",
        path="/v1/projects",
        data_key="projects",
        partition_key="createdTime",
    ),
    "tasks": MotionEndpointConfig(
        name="tasks",
        path="/v1/tasks",
        data_key="tasks",
        # Without this the list only covers the statuses Motion treats as open, so completed
        # work would never reach the warehouse.
        params={"includeAllStatuses": "true"},
    ),
    "recurring_tasks": MotionEndpointConfig(
        name="recurring_tasks",
        path="/v1/recurring-tasks?workspaceId={workspaceId}",
        data_key="tasks",
        primary_keys=["workspaceId", "id"],
        parent=MotionParentConfig(name="workspaces", resolve_param="workspaceId", parent_id_column="workspaceId"),
    ),
    "comments": MotionEndpointConfig(
        name="comments",
        path="/v1/comments?taskId={taskId}",
        data_key="comments",
        primary_keys=["taskId", "id"],
        partition_key="createdAt",
        parent=MotionParentConfig(name="tasks", resolve_param="taskId"),
    ),
    "custom_fields": MotionEndpointConfig(
        name="custom_fields",
        path="/beta/workspaces/{workspaceId}/custom-fields",
        data_key=None,
        primary_keys=["workspaceId", "id"],
        paginated=False,
        parent=MotionParentConfig(name="workspaces", resolve_param="workspaceId", parent_id_column="workspaceId"),
    ),
}

ENDPOINTS = tuple(MOTION_ENDPOINTS.keys())

# Motion documents no server-side timestamp filter on any list endpoint, so every table is a
# full refresh. A client-side cursor would still page through everything against a 12-requests
# per minute limit, which is worse than a plain full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
