from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class OnfleetEndpointConfig:
    name: str
    path: str
    # Only `/tasks/all` is paginated (cursor via `lastId`, 64 rows/page). Every other list
    # endpoint returns the full collection as a bare JSON array in a single response.
    paginated: bool = False
    # Key wrapping the row array on the paginated endpoint (e.g. {"lastId": ..., "tasks": [...]}).
    data_key: Optional[str] = None
    # `/organization` returns a single object rather than an array.
    single_object: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True


# Onfleet timestamps are UNIX epoch **milliseconds** stored as integers, so candidate incremental
# fields are integers even though the UI presents them as datetimes.
#
# Only `/tasks/all` exposes a server-side time filter (`from`/`to`, epoch ms). `from` filters on a
# task's creation time (completion time for tasks in the `completed` state) and results are always
# sorted ascending by creation time, so incremental sync anchors on `timeCreated`. Every other
# endpoint returns a bare array with no time filter and no pagination, so those are full refresh.
#
# Partitioning is intentionally left off: the datetime partitioner interprets an integer partition
# key as epoch *seconds*, which would misbucket Onfleet's epoch-*millisecond* timestamps.
ONFLEET_ENDPOINTS: dict[str, OnfleetEndpointConfig] = {
    "tasks": OnfleetEndpointConfig(
        name="tasks",
        path="/tasks/all",
        paginated=True,
        data_key="tasks",
        incremental_fields=[
            {
                "label": "timeCreated",
                "type": IncrementalFieldType.DateTime,
                "field": "timeCreated",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    "workers": OnfleetEndpointConfig(name="workers", path="/workers"),
    "teams": OnfleetEndpointConfig(name="teams", path="/teams"),
    "hubs": OnfleetEndpointConfig(name="hubs", path="/hubs"),
    "administrators": OnfleetEndpointConfig(name="administrators", path="/admins"),
    "webhooks": OnfleetEndpointConfig(name="webhooks", path="/webhooks"),
    "organization": OnfleetEndpointConfig(name="organization", path="/organization", single_object=True),
}

ENDPOINTS = tuple(ONFLEET_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ONFLEET_ENDPOINTS.items() if config.incremental_fields
}
