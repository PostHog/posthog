from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class HatchetEndpointConfig:
    name: str
    # Tenant-scoped path template. `{tenant}` is filled with the tenant UUID derived from the token.
    path: str
    incremental_fields: list[IncrementalField]
    default_incremental_field: Optional[str] = None
    # Stable creation timestamp to partition by (never a mutable `updated`/`lastSeen` field).
    partition_key: Optional[str] = None
    page_size: int = 100
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Static query params merged into every request (e.g. `only_tasks`, `include_payloads`).
    extra_params: dict[str, str] = field(default_factory=dict)
    # True only when the API exposes a genuine server-side `since`/`until` time window we can
    # advance a watermark against. `since` is required on the workflow-runs/tasks endpoint, so
    # those pass a floor even on full refresh.
    supports_time_window: bool = False
    # `since` is a required query param on this endpoint (workflow-runs); a value is always sent.
    requires_since: bool = False
    # Floor the first incremental backfill (and full refresh) to the last N days instead of the
    # entire retention window, bounding the initial pull.
    default_lookback_days: Optional[int] = None
    # Trailing overlap re-subtracted from the watermark on every incremental run, re-pulling a
    # window of rows so runs/events whose fields mutate after creation are re-read; the delta
    # merge dedupes them on the primary key.
    incremental_lookback: Optional[timedelta] = None
    # All list endpoints wrap results as `{"rows": [...], "pagination": {...}}`.
    response_data_path: str = "rows"
    # Rows arrive newest-first, so we declare desc: the pipeline then persists the incremental
    # watermark only at successful job end (a partial run's max says nothing about the older rows
    # it never reached), and resume replays from the saved offset instead.
    sort_mode: Literal["asc", "desc"] = "asc"


# `since` is required on the workflow-runs/tasks endpoint even for a full refresh. Retention windows
# bound real history anyway, so a fixed far-past floor pulls everything the tenant still retains.
FULL_REFRESH_SINCE_DAYS = 3650

_TIME_WINDOW_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


HATCHET_ENDPOINTS: dict[str, HatchetEndpointConfig] = {
    # Top-level workflow (DAG) runs plus standalone task runs. `only_tasks=false` keeps the
    # DAG-level parent runs; the `tasks` endpoint below drills into the task grain.
    "workflow_runs": HatchetEndpointConfig(
        name="workflow_runs",
        path="/api/v1/stable/tenants/{tenant}/workflow-runs",
        partition_key="created_at",
        incremental_fields=_TIME_WINDOW_INCREMENTAL_FIELDS,
        default_incremental_field="created_at",
        supports_time_window=True,
        requires_since=True,
        default_lookback_days=30,
        # A run's status/output mutate after it is created, and the created_at cursor only refreshes
        # rows at/above the watermark. Re-read a trailing day each run so a run that finishes after
        # newer runs landed is picked up again; merge dedupes on id.
        incremental_lookback=timedelta(days=1),
        sort_mode="desc",
        extra_params={"only_tasks": "false", "include_payloads": "true"},
    ),
    # Individual task-level runs (`only_tasks=true`), including the children of DAG runs.
    "tasks": HatchetEndpointConfig(
        name="tasks",
        path="/api/v1/stable/tenants/{tenant}/workflow-runs",
        partition_key="created_at",
        incremental_fields=_TIME_WINDOW_INCREMENTAL_FIELDS,
        default_incremental_field="created_at",
        supports_time_window=True,
        requires_since=True,
        default_lookback_days=30,
        incremental_lookback=timedelta(days=1),
        sort_mode="desc",
        extra_params={"only_tasks": "true", "include_payloads": "true"},
    ),
    # Events ingested into the tenant (each can trigger workflow runs). `since`/`until` are optional
    # here but still bound the pull; created_at is the incremental cursor.
    "events": HatchetEndpointConfig(
        name="events",
        path="/api/v1/stable/tenants/{tenant}/events",
        partition_key="created_at",
        incremental_fields=_TIME_WINDOW_INCREMENTAL_FIELDS,
        default_incremental_field="created_at",
        supports_time_window=True,
        default_lookback_days=30,
        incremental_lookback=timedelta(days=1),
        sort_mode="desc",
    ),
    # The distinct event keys seen in the tenant. Tiny, timestamp-free reference list, so full
    # refresh only; each row is the key string, keyed on itself.
    "event_keys": HatchetEndpointConfig(
        name="event_keys",
        path="/api/v1/stable/tenants/{tenant}/events/keys",
        incremental_fields=[],
        primary_keys=["key"],
    ),
}

ENDPOINTS = tuple(HATCHET_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in HATCHET_ENDPOINTS.items()
}
