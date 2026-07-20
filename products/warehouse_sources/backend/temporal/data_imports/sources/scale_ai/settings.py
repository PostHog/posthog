from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class ScaleAIEndpointConfig:
    name: str
    path: str
    # Pagination style the endpoint exposes. Tasks use a `next_token` cursor; batches use
    # `limit`/`offset`; projects return the whole list in one response (no pagination).
    pagination: Literal["cursor", "offset", "none"]
    incremental_fields: list[IncrementalField]
    default_incremental_field: Optional[str] = None
    # Stable field to partition by. Always a creation timestamp so partitions never rewrite
    # (Scale exposes no server-side sort, so `updated_at` would move rows between partitions).
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["task_id"])
    page_size: int = 100  # Scale caps `limit` at 100 for tasks
    should_sync_default: bool = True


# Maps a user-selected incremental field to the Scale query parameter that filters on it
# server-side. Tasks accept `updated_after` (updated_at) and `start_time` (created_at); batches
# only accept `start_time` (created_at). Only fields present here can be synced incrementally.
INCREMENTAL_PARAM_BY_FIELD: dict[str, str] = {
    "updated_at": "updated_after",
    "created_at": "start_time",
}


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


SCALE_AI_ENDPOINTS: dict[str, ScaleAIEndpointConfig] = {
    # Tasks are the core operational records (type, status, review results, timestamps). They
    # return newest-first by created_at and support a genuine server-side `updated_after` filter,
    # so incremental sync picks up both new tasks and updates (status/review changes) to old ones.
    "tasks": ScaleAIEndpointConfig(
        name="tasks",
        path="/tasks",
        pagination="cursor",
        primary_keys=["task_id"],
        partition_key="created_at",
        default_incremental_field="updated_at",
        incremental_fields=[_datetime_field("updated_at"), _datetime_field("created_at")],
    ),
    # Batches group tasks. The list endpoint filters only on created_at (`start_time`), which is
    # immutable, so incremental sync catches newly created batches but not status changes to old
    # ones; a full refresh re-reads status for every batch.
    "batches": ScaleAIEndpointConfig(
        name="batches",
        path="/batches",
        pagination="offset",
        primary_keys=["name"],
        partition_key="created_at",
        default_incremental_field="created_at",
        incremental_fields=[_datetime_field("created_at")],
    ),
    # Projects are a small, slowly-changing catalog with no server-side time filter, so they are
    # full-refreshed each sync.
    "projects": ScaleAIEndpointConfig(
        name="projects",
        path="/projects",
        pagination="none",
        primary_keys=["name"],
        partition_key="created_at",
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(SCALE_AI_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SCALE_AI_ENDPOINTS.items()
}
