from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, IncrementalFieldType


@dataclass(frozen=False)
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
    # JSONPath to the row list in a list response. Tasks/batches wrap rows in a `docs` envelope;
    # projects return a bare array (None selects the whole body as the row list).
    data_selector: Optional[str] = "docs"
    # Set for endpoints that only answer for one parent row at a time.
    fanout: Optional[DependentEndpointConfig] = None


# Maps a user-selected incremental field to the Scale query parameter that filters on it
# server-side. Tasks accept `updated_after` (updated_at) and `start_time` (created_at); batches
# only accept `start_time` (created_at). Only fields present here can be synced incrementally.
INCREMENTAL_PARAM_BY_FIELD: dict[str, str] = {
    "updated_at": "updated_after",
    "created_at": "start_time",
}


# Batch names are chosen by the customer and go into a URL path, so the parent rows carry a
# percent-encoded copy for the fan-out to bind.
ENCODED_NAME_FIELD = "_encoded_name"


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
        data_selector=None,
    ),
    # Fixless audits can only be read per task (`task_id` is required), so this fans out over the
    # task list. An audit needs a task response, so only completed tasks are listed. There is no
    # server-side time filter on audits, and the fan-out sends one request per completed task, so
    # it is a full refresh and off by default.
    "audits": ScaleAIEndpointConfig(
        name="audits",
        path="/audits?task_id={task_id}",
        pagination="none",
        primary_keys=["id"],
        partition_key="created_at",
        incremental_fields=[],
        data_selector=None,
        should_sync_default=False,
        fanout=DependentEndpointConfig(
            parent_name="tasks",
            resolve_param="task_id",
            resolve_field="task_id",
            include_from_parent=[],
            parent_params={"limit": 100, "status": "completed"},
            # A task deleted between the listing and this request has no audits to read.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    # The status response holds no batch name, so the name is copied from the parent row.
    "batch_statuses": ScaleAIEndpointConfig(
        name="batch_statuses",
        path="/batches/{batch_name}/status",
        pagination="none",
        primary_keys=["batch_name"],
        incremental_fields=[],
        data_selector=None,
        fanout=DependentEndpointConfig(
            parent_name="batches",
            resolve_param="batch_name",
            resolve_field=ENCODED_NAME_FIELD,
            include_from_parent=["name"],
            parent_field_renames={"name": "batch_name"},
            parent_params={"limit": 100},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(SCALE_AI_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SCALE_AI_ENDPOINTS.items()
}
