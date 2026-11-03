from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass  # nosemgrep: prefer-frozen-dataclasses -- pre-existing; new field shifts the backlog finding into diff
class TriggerDevEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    # "cursor"     -> page[after]/pagination.next cursor pagination (runs, errors, deployments, waitpoints).
    # "page"       -> classic page/perPage pagination (schedules, queues).
    # "run_fanout" -> one request per run, walking the runs endpoint as the parent.
    pagination: Literal["cursor", "page", "run_fanout"] = "page"
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
    # Query param that takes the created-at lower bound on the first cursor page.
    created_from_param: Optional[str] = None
    extra_params: dict[str, str] = field(default_factory=dict)
    # Fields dropped from every row before it is yielded.
    excluded_fields: tuple[str, ...] = ()


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
        created_from_param="filter[createdAt][from]",
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
    # Error groups: failed runs grouped by fingerprint per task. Ordered by occurrence count with no
    # creation filter, and status / count / lastSeen keep changing, so full refresh each sync. The API
    # counts occurrences over the last day by default; the wide period asks for every group in the
    # plan's log retention, which the server clamps to silently.
    "errors": TriggerDevEndpointConfig(
        name="errors",
        path="/api/v1/errors",
        pagination="cursor",
        partition_key="firstSeen",
        extra_params={"filter[period]": "365d"},
        # The id is derived from the fingerprint alone, and the same fingerprint can group per task.
        primary_keys=["id", "taskIdentifier"],
        incremental_fields=[],
    ),
    # Deployments arrive newest-first. Status moves from BUILDING to DEPLOYED / FAILED / TIMED_OUT
    # within hours, so a one-day lookback re-reads deployments that were still in progress.
    "deployments": TriggerDevEndpointConfig(
        name="deployments",
        path="/api/v1/deployments",
        pagination="cursor",
        default_incremental_field="createdAt",
        partition_key="createdAt",
        sort_mode="desc",
        incremental_lookback=timedelta(days=1),
        created_from_param="from",
        incremental_fields=[
            {
                "label": "createdAt",
                "type": IncrementalFieldType.DateTime,
                "field": "createdAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Waitpoint tokens arrive newest-first. A token can wait on a person or an external system for
    # days, so the lookback is wider than for runs to pick up late completions.
    "waitpoint_tokens": TriggerDevEndpointConfig(
        name="waitpoint_tokens",
        path="/api/v1/waitpoints/tokens",
        pagination="cursor",
        default_incremental_field="createdAt",
        partition_key="createdAt",
        sort_mode="desc",
        incremental_lookback=timedelta(days=7),
        created_from_param="filter[createdAt][from]",
        # The callback URL completes the token without an API key, so it must not land in the warehouse.
        excluded_fields=("url",),
        incremental_fields=[
            {
                "label": "createdAt",
                "type": IncrementalFieldType.DateTime,
                "field": "createdAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # OTel span events per run, fetched once per run while walking the runs endpoint newest-first.
    # Each row carries the parent run's id and createdAt, so the sync is incremental on the parent's
    # creation time with the same lookback as runs. Off by default: it costs one request per run.
    "run_events": TriggerDevEndpointConfig(
        name="run_events",
        path="/api/v1/runs/{run_id}/events",
        pagination="run_fanout",
        default_incremental_field="_runs_createdAt",
        partition_key="_runs_createdAt",
        sort_mode="desc",
        incremental_lookback=timedelta(days=3),
        primary_keys=["_runs_id", "spanId"],
        should_sync_default=False,
        incremental_fields=[
            {
                "label": "_runs_createdAt",
                "type": IncrementalFieldType.DateTime,
                "field": "_runs_createdAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(TRIGGER_DEV_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TRIGGER_DEV_ENDPOINTS.items()
}
