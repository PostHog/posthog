"""Shadow-scheduler decision logic: scope, cadence math, and per-window evaluation.

A schema is in scope for scheduling when all of these hold:

- ``should_sync`` is true and ``sync_frequency_interval`` is set,
- the schema is not soft-deleted and its source is not soft-deleted,
- the source's ``access_method`` is not ``direct`` (mirrors
  ``ExternalDataSource.supports_scheduled_sync``).

``cdc_halted`` is deliberately not a scope condition: a halted CDC schema keeps
its state row and gets a ``skip_cdc_halted`` decision at fire time, so the
shadow report can show what Temporal's SKIP overlap policy hides.

Overlap is decided from the queue's own job state, never from
``ExternalDataJob`` rows: a run that dies without a status update can leave its
row in RUNNING, and that row must not block the schedule. Each scheduled kind
declares its queue lane and its ``OverlapPolicy``; ``sync.extract`` uses
``SKIP``, as the Temporal schedules do. A ``skip_overlap`` decision means the
policy refused the window because of the schema's live queue jobs.

A schema of a firing team gets a real job. The job insert runs the overlap
policy and the window's dedup key in the same statement, so the decision is
``fired``, ``skip_overlap`` or ``skip_duplicate`` as the insert answered. Every
other schema keeps the shadow decision, which reads the same policy without an
insert.

Due times are epoch-aligned integers, matching Temporal's
``ScheduleIntervalSpec`` semantics: a schedule fires at ``n * interval +
offset`` (UTC epoch), where the offset ports ``get_sync_schedule`` exactly,
including its deterministic per-schema jitter and its dropping of
``sync_time_of_day`` seconds.
"""

from __future__ import annotations

import uuid
import random
from datetime import UTC, datetime, time, timedelta
from typing import Any

import psycopg

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async_pool

from products.warehouse_sources.backend.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.queue_runs.payloads import (
    EXTRACT_LANE,
    SYNC_EXTRACT_KIND,
    SyncExtractPayload,
    SyncTrigger,
    group_key,
    scheduled_workflow_id,
)
from products.warehouse_sources_queue.backend.sdk import (
    DecisionRecord,
    DueSchedule,
    GroupJobState,
    InsertRefusal,
    InsertResult,
    JobsTable,
    OverlapPolicy,
    overlap_allows,
)

SCHEDULER_LANE = "scheduler"
TICK_SLOT_KEY = "tick-slot"
REFRESH_SLOT_KEY = "refresh-slot"

DECISION_WOULD_FIRE = "would_fire"
DECISION_FIRED = "fired"
DECISION_SKIP_OVERLAP = "skip_overlap"
DECISION_SKIP_DUPLICATE = "skip_duplicate"
DECISION_SKIP_CDC_HALTED = "skip_cdc_halted"
DECISION_SKIP_OUT_OF_SCOPE = "skip_out_of_scope"

SKIP_REASONS = {
    DECISION_SKIP_OVERLAP: "overlap_running",
    DECISION_SKIP_DUPLICATE: "duplicate_job",
    DECISION_SKIP_CDC_HALTED: "cdc_halted",
    DECISION_SKIP_OUT_OF_SCOPE: "out_of_scope",
}

_REFUSAL_DECISIONS = {
    InsertRefusal.OVERLAP: DECISION_SKIP_OVERLAP,
    InsertRefusal.DEDUP: DECISION_SKIP_DUPLICATE,
}


@frozen
class ScheduledKind:
    """How the scheduler enqueues one kind: its queue lane and overlap policy."""

    lane: str
    overlap_policy: OverlapPolicy


SCHEDULED_KINDS: dict[str, ScheduledKind] = {
    SYNC_EXTRACT_KIND: ScheduledKind(lane=EXTRACT_LANE, overlap_policy=OverlapPolicy.SKIP),
}


@frozen
class SchemaCadence:
    interval_seconds: int
    offset_seconds: int


@frozen
class InScopeSchema:
    schema_id: str
    team_id: int
    interval: timedelta
    sync_time_of_day: time | None


@frozen
class DueScope:
    """What the due scan reads for a schema that is still in scope."""

    source_id: str
    sync_type_config: dict | None


@frozen
class _Window:
    row: DueSchedule
    cadence: SchemaCadence
    fire: int


@frozen
class EvaluationResult:
    records: tuple[DecisionRecord, ...]
    missed_windows: int


def _jitter_minutes(max_jitter: timedelta, rng: random.Random) -> int:
    """Exact port of ``service._jitter_timedelta``: one uniform draw, split into
    whole hours times sixty plus whole minutes (seconds truncated)."""
    total_seconds = max_jitter.total_seconds()
    jitter_seconds = rng.uniform(0, total_seconds)
    return int(jitter_seconds // 3600) * 60 + int((jitter_seconds % 3600) // 60)


def schedule_offset(schema_id: str, interval: timedelta, sync_time_of_day: time | None) -> int:
    """The schema's Temporal schedule offset in whole seconds.

    Ports ``get_sync_schedule`` + ``to_temporal_schedule``: an explicit
    ``sync_time_of_day`` contributes ``hour*60 + minute`` minutes (seconds
    dropped), otherwise a deterministic jitter seeded on the schema id is
    bucketed by interval; either way the minutes reduce modulo the interval.
    The rng draw and the elif chain must stay bit-identical to the service's,
    because parity with live Temporal schedules is the whole point of shadow
    mode.
    """
    if sync_time_of_day is not None:
        minutes = sync_time_of_day.hour * 60 + sync_time_of_day.minute
    else:
        rng = random.Random(str(schema_id))
        jitter_minutes = 0
        if interval <= timedelta(minutes=5):
            jitter_minutes = _jitter_minutes(timedelta(minutes=5), rng)
        elif interval <= timedelta(minutes=30):
            jitter_minutes = _jitter_minutes(timedelta(minutes=30), rng)
        elif interval <= timedelta(hours=1):
            jitter_minutes = _jitter_minutes(timedelta(hours=1), rng)
        elif interval <= timedelta(hours=6):
            jitter_minutes = _jitter_minutes(timedelta(hours=6), rng)
        elif interval <= timedelta(hours=12):
            jitter_minutes = _jitter_minutes(timedelta(hours=12), rng)
        elif interval <= timedelta(days=1):
            jitter_minutes = _jitter_minutes(timedelta(days=1), rng)
        minutes = jitter_minutes
    return int((timedelta(minutes=minutes) % interval).total_seconds())


def latest_fire_at(now: int, cadence: SchemaCadence) -> int:
    """The most recent epoch second at which this cadence fired (<= now)."""
    return ((now - cadence.offset_seconds) // cadence.interval_seconds) * cadence.interval_seconds + (
        cadence.offset_seconds
    )


def window_boundary(fire: int, cadence: SchemaCadence) -> int:
    """The fire's offset-free cadence boundary, retained for comparison."""
    return fire - cadence.offset_seconds


def next_due_after(now: int, cadence: SchemaCadence) -> int:
    return latest_fire_at(now, cadence) + cadence.interval_seconds


def cdc_halted_from_config(sync_type_config: dict | None) -> bool:
    """Mirror of ``ExternalDataSchema.cdc_halted``, evaluated on the fetched
    ``sync_type_config`` dict so the due scan needs no model instances."""
    config = sync_type_config or {}
    return bool(config.get("cdc_broken")) or bool(config.get("cdc_extraction_paused"))


def _in_scope_queryset():
    return (
        # Unscoped manager on purpose: the scheduler scans the whole fleet.
        # `deleted` is nullable, so exclude(deleted=True), not filter(deleted=False).
        ExternalDataSchema.objects.filter(should_sync=True, sync_frequency_interval__isnull=False)
        .exclude(deleted=True)
        .exclude(source__deleted=True)
        .exclude(source__access_method=ExternalDataSource.AccessMethod.DIRECT)
    )


def fetch_in_scope_schema_page(after_id: str | None, limit: int) -> list[InScopeSchema]:
    """One id-ordered page of in-scope schemas. Read-only; call via the async wrapper.

    Keyset pagination, not ``QuerySet.iterator()``: behind PgBouncer Django
    disables server-side cursors, and ``iterator()`` then loads the whole
    result set into memory before it yields the first row.
    """
    queryset = _in_scope_queryset()
    if after_id is not None:
        queryset = queryset.filter(id__gt=after_id)
    rows = queryset.order_by("id").values_list("id", "team_id", "sync_frequency_interval", "sync_time_of_day")[:limit]
    return [
        InScopeSchema(schema_id=str(schema_id), team_id=team_id, interval=interval, sync_time_of_day=sync_time)
        for schema_id, team_id, interval, sync_time in rows
    ]


def _fetch_due_scope(schema_ids: list[str]) -> dict[str, DueScope]:
    rows = _in_scope_queryset().filter(id__in=schema_ids).values_list("id", "source_id", "sync_type_config")
    return {
        str(schema_id): DueScope(source_id=str(source_id), sync_type_config=config)
        for schema_id, source_id, config in rows
    }


def window_dedup_key(schema_id: str, due_at: datetime) -> str:
    """One job per schema and fire window, however often the window is evaluated."""
    return f"{schema_id}:{int(due_at.timestamp())}"


def _scheduled_job(row: DueSchedule, source_id: str, due_at: datetime) -> dict[str, Any]:
    payload = SyncExtractPayload(
        team_id=row.team_id,
        schema_id=uuid.UUID(row.schedule_key),
        source_id=uuid.UUID(source_id),
        trigger=SyncTrigger.SCHEDULE,
        # A Temporal schedule always starts its runs as billable.
        billable=True,
        reset_pipeline=None,
        workflow_id=scheduled_workflow_id(row.schedule_key, due_at),
        due_at=due_at,
    )
    return {
        "kind": row.kind,
        "lane": SCHEDULED_KINDS[row.kind].lane,
        "group_key": payload.group_key,
        "team_id": row.team_id,
        "payload": payload.to_json(),
        "dedup_key": window_dedup_key(row.schedule_key, due_at),
    }


async def _enqueue_windows(
    conn: psycopg.AsyncConnection[Any], windows: list[tuple[_Window, str]]
) -> dict[DueSchedule, InsertResult]:
    """Insert one job per window, one statement per kind. The policy guards run in the insert."""
    results: dict[DueSchedule, InsertResult] = {}
    for kind in sorted({window.row.kind for window, _ in windows}):
        of_kind = [(window, source_id) for window, source_id in windows if window.row.kind == kind]
        inserted = await JobsTable.insert_many_guarded(
            conn,
            [
                _scheduled_job(window.row, source_id, datetime.fromtimestamp(window.fire, tz=UTC))
                for window, source_id in of_kind
            ],
            overlap_policy=SCHEDULED_KINDS[kind].overlap_policy,
        )
        for (window, _), result in zip(of_kind, inserted, strict=True):
            results[window.row] = result
    return results


async def _fetch_group_job_states(
    conn: psycopg.AsyncConnection[Any], due: list[DueSchedule]
) -> dict[DueSchedule, GroupJobState]:
    """Live queue-job state per due row. One query per kind."""
    states: dict[DueSchedule, GroupJobState] = {}
    for kind in sorted({row.kind for row in due}):
        rows = [row for row in due if row.kind == kind]
        by_group = await JobsTable.get_group_job_states(
            conn,
            kind=kind,
            lane=SCHEDULED_KINDS[kind].lane,
            group_keys=[group_key(row.team_id, row.schedule_key) for row in rows],
        )
        for row in rows:
            states[row] = by_group[group_key(row.team_id, row.schedule_key)]
    return states


async def evaluate_due(
    conn: psycopg.AsyncConnection[Any],
    due: list[DueSchedule],
    now_epoch: int,
    *,
    firing_team_ids: frozenset[int] = frozenset(),
) -> EvaluationResult:
    """Decide, per due schema, what the scheduler does with its latest window.

    ``conn`` is a connection to the queue database, where the job tables live.
    Call it inside the tick transaction, so the jobs it enqueues commit with the
    decisions and the state advance. Schemas of ``firing_team_ids`` get a real
    job; the rest get the shadow decision only.

    Records exactly one decision per schema, for the latest window only: a tick
    late by several intervals counts the earlier windows on the missed-windows
    metric rather than back-filling decisions Temporal never took either (its
    interval spec fires at most once per boundary that passes while up).
    """
    if not due:
        return EvaluationResult(records=(), missed_windows=0)

    due_ids = [row.schedule_key for row in due]
    scope = await database_sync_to_async_pool(_fetch_due_scope)(due_ids)

    windows: list[_Window] = []
    missed_windows = 0
    for row in due:
        cadence = SchemaCadence(interval_seconds=row.interval_seconds, offset_seconds=row.offset_seconds)
        fire = latest_fire_at(now_epoch, cadence)
        missed_windows += max(0, (fire - int(row.next_due_at.timestamp())) // cadence.interval_seconds)
        windows.append(_Window(row=row, cadence=cadence, fire=fire))

    decisions: dict[DueSchedule, str] = {}
    to_fire: list[tuple[_Window, str]] = []
    shadow: list[_Window] = []
    for window in windows:
        row = window.row
        due_scope = scope.get(row.schedule_key)
        if due_scope is None:
            decisions[row] = DECISION_SKIP_OUT_OF_SCOPE
        elif row.team_id not in firing_team_ids:
            shadow.append(window)
        elif cdc_halted_from_config(due_scope.sync_type_config):
            decisions[row] = DECISION_SKIP_CDC_HALTED
        else:
            to_fire.append((window, due_scope.source_id))

    group_states = await _fetch_group_job_states(conn, [window.row for window in shadow])
    for window in shadow:
        row = window.row
        if not overlap_allows(SCHEDULED_KINDS[row.kind].overlap_policy, group_states[row]):
            decisions[row] = DECISION_SKIP_OVERLAP
        elif cdc_halted_from_config(scope[row.schedule_key].sync_type_config):
            decisions[row] = DECISION_SKIP_CDC_HALTED
        else:
            decisions[row] = DECISION_WOULD_FIRE

    job_ids: dict[DueSchedule, str] = {}
    for row, result in (await _enqueue_windows(conn, to_fire)).items():
        if result.job_id is not None:
            decisions[row] = DECISION_FIRED
            job_ids[row] = result.job_id
        else:
            assert result.refusal is not None
            decisions[row] = _REFUSAL_DECISIONS[result.refusal]

    records = tuple(
        DecisionRecord(
            team_id=window.row.team_id,
            kind=window.row.kind,
            schedule_key=window.row.schedule_key,
            window_boundary=datetime.fromtimestamp(window_boundary(window.fire, window.cadence), tz=UTC),
            due_at=datetime.fromtimestamp(window.fire, tz=UTC),
            decision=decisions[window.row],
            interval_seconds=window.cadence.interval_seconds,
            late_seconds=float(now_epoch - window.fire),
            job_id=job_ids.get(window.row),
        )
        for window in windows
    )
    return EvaluationResult(records=records, missed_windows=missed_windows)
