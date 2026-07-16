from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class WindmillEndpointConfig:
    name: str
    # Path relative to the workspace root (``{base}/api/w/{workspace}``).
    path: str
    primary_keys: list[str]
    # Windmill list endpoints paginate with 1-based ``page`` + ``per_page`` and return bare JSON
    # arrays, so we walk pages until one comes back short. ``listUsers`` is the one exception: it
    # ignores pagination params and returns every member in a single array, so paging it would
    # re-request the same full list forever. Those endpoints set ``paginated=False``.
    paginated: bool = True
    # Whether the endpoint accepts the ``order_desc`` param. When it does we request ascending
    # order (``order_desc=false``) so newly inserted rows land at the end of the result set and
    # don't shift the offsets of pages we've already walked mid-sync.
    supports_order_desc: bool = False
    # Stable (immutable) datetime field for partitioning. Only a creation timestamp — never an
    # ``edited_at``/``last_*`` field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    partition_format: PartitionFormat = "month"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Maps an incremental field name -> the server-side "after" (exclusive) query param that
    # filters on it. Only set for endpoints Windmill genuinely filters server-side. When empty the
    # endpoint is full-refresh only.
    incremental_after_params: dict[str, str] = field(default_factory=dict)
    should_sync_default: bool = True
    description: Optional[str] = None


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


WINDMILL_ENDPOINTS: dict[str, WindmillEndpointConfig] = {
    # Completed jobs are immutable execution records, so they are the one genuinely incremental
    # stream. Windmill exposes exclusive ``created_after`` / ``started_after`` filters; we request
    # ascending order and advance the watermark from the chosen cursor field.
    "completed_jobs": WindmillEndpointConfig(
        name="completed_jobs",
        path="/jobs/completed/list",
        primary_keys=["id"],
        supports_order_desc=True,
        partition_key="created_at",
        partition_format="day",
        incremental_fields=[_datetime_field("created_at"), _datetime_field("started_at")],
        incremental_after_params={"created_at": "created_after", "started_at": "started_after"},
        description="Execution history of finished jobs (scripts, flows, previews) with status, duration, and script path. Immutable, so supports incremental sync.",
    ),
    # Queued/running jobs are transient (they move to completed_jobs when they finish), so each
    # sync captures a fresh snapshot via full refresh.
    "queued_jobs": WindmillEndpointConfig(
        name="queued_jobs",
        path="/jobs/queue/list",
        primary_keys=["id"],
        supports_order_desc=True,
        partition_key="created_at",
        partition_format="day",
        description="Snapshot of jobs currently queued or running. Full refresh each sync since queued jobs are transient.",
    ),
    "scripts": WindmillEndpointConfig(
        name="scripts",
        path="/scripts/list",
        primary_keys=["hash"],
        supports_order_desc=True,
        partition_key="created_at",
        description="Deployed scripts, one row per latest version per path. The list endpoint has no updated-since filter, so it is full-refresh only.",
    ),
    "flows": WindmillEndpointConfig(
        name="flows",
        path="/flows/list",
        primary_keys=["path"],
        supports_order_desc=True,
        description="Deployed flows (multi-step workflows), one row per path.",
    ),
    "apps": WindmillEndpointConfig(
        name="apps",
        path="/apps/list",
        primary_keys=["id"],
        supports_order_desc=True,
        description="Deployed apps (internal UIs built on Windmill), one row per path.",
    ),
    "schedules": WindmillEndpointConfig(
        name="schedules",
        path="/schedules/list",
        primary_keys=["path"],
        description="Cron schedules that trigger scripts and flows.",
    ),
    "resources": WindmillEndpointConfig(
        name="resources",
        path="/resources/list",
        primary_keys=["path"],
        description="Resource definitions (connection configs). The list endpoint returns metadata; secret values are not included.",
    ),
    "users": WindmillEndpointConfig(
        name="users",
        path="/users/list",
        primary_keys=["email"],
        paginated=False,
        partition_key="created_at",
        description="Workspace members. Returned in a single unpaginated response.",
    ),
    # Audit logs are a Windmill Enterprise Edition feature and require a workspace-admin token; the
    # endpoint returns an empty list on Community Edition. Ordering is not part of the public API,
    # so this stays full refresh rather than risk a corrupt incremental watermark.
    "audit_logs": WindmillEndpointConfig(
        name="audit_logs",
        path="/audit/list",
        primary_keys=["id"],
        partition_key="timestamp",
        partition_format="week",
        should_sync_default=False,
        description="Audit log entries. Windmill Enterprise Edition only and requires a workspace-admin token (empty on Community Edition).",
    ),
}

ENDPOINTS = tuple(WINDMILL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in WINDMILL_ENDPOINTS.items()
}
