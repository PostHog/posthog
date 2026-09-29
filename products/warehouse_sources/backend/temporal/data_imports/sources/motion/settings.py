from dataclasses import field
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField


@frozen
class MotionEndpointConfig:
    name: str
    path: str
    # Key the rows sit under in the response envelope, alongside `meta`.
    data_key: str
    primary_key: str = "id"
    # Extra query params sent on every page.
    params: dict[str, Any] = field(default_factory=dict)
    partition_key: Optional[str] = None


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
}

ENDPOINTS = tuple(MOTION_ENDPOINTS.keys())

# Motion documents no server-side timestamp filter on any list endpoint, so every table is a
# full refresh. A client-side cursor would still page through everything against a 12-requests
# per minute limit, which is worse than a plain full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
