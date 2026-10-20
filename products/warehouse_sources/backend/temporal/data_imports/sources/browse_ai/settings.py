from dataclasses import field
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.browse.ai/v2"
AUTH_ERROR = "Your Browse AI API key is invalid or expired. Generate a new key and reconnect."
PERMISSION_ERROR = "Your Browse AI API key cannot access this resource. Check the key's permissions and reconnect."


@frozen
class BrowseAIEndpoint:
    name: str
    path: str
    data_selector: str
    primary_keys: tuple[str, ...]
    pagination_path: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    partition_key: str = "createdAt"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    page_size: int = 10
    fanout: DependentEndpointConfig | None = None


def robot_fanout() -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name="robots",
        resolve_param="robot_id",
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": "robotId"},
    )


ENDPOINTS = {
    "robots": BrowseAIEndpoint(name="robots", path="robots", data_selector="robots.items", primary_keys=("id",)),
    "tasks": BrowseAIEndpoint(
        name="tasks",
        path="robots/{robot_id}/tasks",
        data_selector="result.robotTasks.items",
        primary_keys=("robotId", "id"),
        pagination_path="result.robotTasks",
        params={"pageSize": 10, "sort": "createdAt", "includeRetried": "true"},
        fanout=robot_fanout(),
    ),
    "monitors": BrowseAIEndpoint(
        name="monitors",
        path="robots/{robot_id}/monitors",
        data_selector="monitors.items",
        primary_keys=("robotId", "id"),
        fanout=robot_fanout(),
    ),
    "bulk_runs": BrowseAIEndpoint(
        name="bulk_runs",
        path="robots/{robot_id}/bulk-runs",
        data_selector="result.items",
        primary_keys=("robotId", "id"),
        pagination_path="result",
        fanout=robot_fanout(),
    ),
}

# Creation-time filtering needs a live-account check before it can safely advance a task watermark.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
