from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class TriggerDevEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    # "cursor" -> the runs endpoint's page[after]/pagination.next cursor pagination.
    # "page"   -> classic page/perPage pagination (schedules, queues).
    pagination: Literal["cursor", "page"] = "page"
    default_incremental_field: Optional[str] = None
    # Field to partition by. Must be a STABLE creation timestamp (never updatedAt) so partitions
    # aren't rewritten every sync.
    partition_key: Optional[str] = None
    page_size: int = 100  # runs cap at 100; classic endpoints accept the same size comfortably
    sort_mode: Literal["asc", "desc"] = "asc"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Safety overlap subtracted from the incremental watermark each run. Runs are created immutable,
    # but their status / updatedAt / cost fields keep mutating after creation, and there is no
    # updated-since filter — so we re-pull a trailing window of recently created runs to pick up those
    # late transitions. Merge dedupes the re-pulled rows on the primary key.
    incremental_lookback: Optional[timedelta] = None


TRIGGER_DEV_ENDPOINTS: dict[str, TriggerDevEndpointConfig] = {
    # Task runs: the execution history. Cursor pagination (page[after] = pagination.next), returned
    # newest-first by createdAt with no sort param, so we sync incrementally by walking newest-first
    # and stopping once we cross below the watermark (see trigger_dev.py). createdAt is immutable, so
    # it is the stable partition/cursor key; the 3-day lookback re-reads recent runs to catch status
    # changes that land after the run was first synced.
    "runs": TriggerDevEndpointConfig(
        name="runs",
        path="/api/v1/runs",
        pagination="cursor",
        default_incremental_field="createdAt",
        partition_key="createdAt",
        sort_mode="desc",
        incremental_lookback=timedelta(days=3),
        incremental_fields=[
            {
                "label": "createdAt",
                "type": IncrementalFieldType.DateTime,
                "field": "createdAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Schedules are a small, mutable config set (active flag, cron expression, nextRun) with no
    # creation timestamp or server-side time filter, so full refresh each sync.
    "schedules": TriggerDevEndpointConfig(
        name="schedules",
        path="/api/v1/schedules",
        pagination="page",
        incremental_fields=[],
    ),
    # Queues report live counters (running / queued / paused) that only make sense as a current
    # snapshot, and there is no timestamp to sync on, so full refresh each sync.
    "queues": TriggerDevEndpointConfig(
        name="queues",
        path="/api/v1/queues",
        pagination="page",
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(TRIGGER_DEV_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TRIGGER_DEV_ENDPOINTS.items()
}
