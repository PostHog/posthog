"""Shadow-scheduler decision logic: scope, cadence math, and per-window evaluation.

A schema is in scope for scheduling when all of these hold:

- ``should_sync`` is true and ``sync_frequency_interval`` is set,
- the schema is not soft-deleted and its source is not soft-deleted,
- the source's ``access_method`` is not ``direct`` (mirrors
  ``ExternalDataSource.supports_scheduled_sync``).

``cdc_halted`` is deliberately not a scope condition: a halted CDC schema keeps
its state row and gets a ``skip_cdc_halted`` decision at fire time, so the
shadow report can show what Temporal's SKIP overlap policy hides.

Due times are epoch-aligned integers, matching Temporal's
``ScheduleIntervalSpec`` semantics: a schedule fires at ``n * interval +
offset`` (UTC epoch), where the offset ports ``get_sync_schedule`` exactly,
including its deterministic per-schema jitter and its dropping of
``sync_time_of_day`` seconds.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, time, timedelta

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async_pool

from products.warehouse_sources.backend.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources_queue.backend.sdk import DecisionRecord, DueSchedule

SCHEDULER_LANE = "scheduler"
TICK_SLOT_KEY = "tick-slot"
REFRESH_SLOT_KEY = "refresh-slot"

DECISION_WOULD_FIRE = "would_fire"
DECISION_SKIP_OVERLAP = "skip_overlap"
DECISION_SKIP_CDC_HALTED = "skip_cdc_halted"
DECISION_SKIP_OUT_OF_SCOPE = "skip_out_of_scope"

SKIP_REASONS = {
    DECISION_SKIP_OVERLAP: "overlap_running",
    DECISION_SKIP_CDC_HALTED: "cdc_halted",
    DECISION_SKIP_OUT_OF_SCOPE: "out_of_scope",
}


@frozen
class SchemaCadence:
    interval_seconds: int
    offset_seconds: int


@frozen
class EvaluationResult:
    records: tuple[DecisionRecord, ...]
    missed_windows: int


def _jitter_timedelta(max_jitter: timedelta, rng: random.Random) -> tuple[int, int]:
    """Exact port of ``service._jitter_timedelta``: one uniform draw, split into
    whole hours and whole minutes (seconds truncated)."""
    total_seconds = max_jitter.total_seconds()
    jitter_seconds = rng.uniform(0, total_seconds)
    return (int(jitter_seconds // 3600), int((jitter_seconds % 3600) // 60))


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
        hours = 0
        jitter_minutes = 0
        if interval <= timedelta(minutes=5):
            hours, jitter_minutes = _jitter_timedelta(timedelta(minutes=5), rng)
        elif interval <= timedelta(minutes=30):
            hours, jitter_minutes = _jitter_timedelta(timedelta(minutes=30), rng)
        elif interval <= timedelta(hours=1):
            hours, jitter_minutes = _jitter_timedelta(timedelta(hours=1), rng)
        elif interval <= timedelta(hours=6):
            hours, jitter_minutes = _jitter_timedelta(timedelta(hours=6), rng)
        elif interval <= timedelta(hours=12):
            hours, jitter_minutes = _jitter_timedelta(timedelta(hours=12), rng)
        elif interval <= timedelta(days=1):
            hours, jitter_minutes = _jitter_timedelta(timedelta(days=1), rng)
        minutes = hours * 60 + jitter_minutes
    return int((timedelta(minutes=minutes) % interval).total_seconds())


def latest_fire_at(now: int, cadence: SchemaCadence) -> int:
    """The most recent epoch second at which this cadence fired (<= now)."""
    return ((now - cadence.offset_seconds) // cadence.interval_seconds) * cadence.interval_seconds + (
        cadence.offset_seconds
    )


def window_boundary(fire: int, cadence: SchemaCadence) -> int:
    """The fire's offset-free window identity; phase 3 dedups enqueues on
    (schema_id, window_boundary), so it must not move when the offset does."""
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


def fetch_in_scope_schemas() -> list[tuple[str, int, timedelta, time | None]]:
    """Every schema the scheduler would manage: (schema_id, team_id, interval,
    sync_time_of_day). Read-only fleet-wide scan; call via the async wrapper."""
    rows = _in_scope_queryset().values_list("id", "team_id", "sync_frequency_interval", "sync_time_of_day")
    return [
        (str(schema_id), team_id, interval, sync_time)
        for schema_id, team_id, interval, sync_time in rows.iterator(chunk_size=1000)
    ]


def _fetch_due_scope(schema_ids: list[str]) -> dict[str, dict | None]:
    rows = _in_scope_queryset().filter(id__in=schema_ids).values_list("id", "sync_type_config")
    return {str(schema_id): config for schema_id, config in rows}


def _fetch_running_schema_ids(schema_ids: list[str]) -> set[str]:
    rows = (
        ExternalDataJob.objects.filter(schema_id__in=schema_ids, status=ExternalDataJob.Status.RUNNING)
        .values_list("schema_id", flat=True)
        .distinct()
    )
    return {str(schema_id) for schema_id in rows}


async def evaluate_due(due: list[DueSchedule], now_epoch: int) -> EvaluationResult:
    """Decide, per due schema, what a real scheduler would have done.

    Records exactly one decision per schema, for the latest window only: a tick
    late by several intervals counts the earlier windows on the missed-windows
    metric rather than back-filling decisions Temporal never took either (its
    interval spec fires at most once per boundary that passes while up).
    """
    if not due:
        return EvaluationResult(records=(), missed_windows=0)

    due_ids = [row.schema_id for row in due]
    scope_config = await database_sync_to_async_pool(_fetch_due_scope)(due_ids)
    running = await database_sync_to_async_pool(_fetch_running_schema_ids)(due_ids)

    records: list[DecisionRecord] = []
    missed_windows = 0
    for row in due:
        cadence = SchemaCadence(interval_seconds=row.interval_seconds, offset_seconds=row.offset_seconds)
        fire = latest_fire_at(now_epoch, cadence)
        stored_due_epoch = int(row.next_due_at.timestamp())
        missed_windows += max(0, (fire - stored_due_epoch) // cadence.interval_seconds)

        if row.schema_id not in scope_config:
            decision = DECISION_SKIP_OUT_OF_SCOPE
        elif row.schema_id in running:
            decision = DECISION_SKIP_OVERLAP
        elif cdc_halted_from_config(scope_config[row.schema_id]):
            decision = DECISION_SKIP_CDC_HALTED
        else:
            decision = DECISION_WOULD_FIRE

        records.append(
            DecisionRecord(
                team_id=row.team_id,
                schema_id=row.schema_id,
                window_boundary=datetime.fromtimestamp(window_boundary(fire, cadence), tz=UTC),
                due_at=datetime.fromtimestamp(fire, tz=UTC),
                decision=decision,
                interval_seconds=cadence.interval_seconds,
                late_seconds=float(now_epoch - fire),
            )
        )
    return EvaluationResult(records=tuple(records), missed_windows=missed_windows)
