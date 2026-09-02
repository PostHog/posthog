"""Shadow-scheduler tick loop: leader election, refresh, due scan, decisions.

Every pod runs the same loop; the tick sentinel single-flights each tick across
the fleet, so followers only heartbeat. The scheduler writes decisions and
metrics but starts no syncs — Temporal schedules stay the only thing that runs
work while shadow mode is compared against them.
"""

from __future__ import annotations

import time
import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import structlog
from prometheus_client import Counter, Gauge, Histogram

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async_pool

from products.warehouse_sources.backend.scheduling.shadow import (
    DECISION_SKIP_OUT_OF_SCOPE,
    DECISION_WOULD_FIRE,
    REFRESH_SLOT_KEY,
    SCHEDULER_LANE,
    SKIP_REASONS,
    TICK_SLOT_KEY,
    SchemaCadence,
    evaluate_due,
    fetch_in_scope_schemas,
    next_due_after,
    schedule_offset,
)
from products.warehouse_sources_queue.backend.sdk import DueSchedule, JobsTable, SchedulerStateTable

logger = structlog.get_logger(__name__)

UPSERT_BATCH_SIZE = 1000

WOULD_FIRE_TOTAL = Counter(
    "warehouse_pg_scheduler_would_fire_total",
    "Windows the shadow scheduler would have fired a sync for",
)

SKIPS_TOTAL = Counter(
    "warehouse_pg_scheduler_skips_total",
    "Windows the shadow scheduler would have skipped",
    labelnames=["reason"],
)

DUPLICATE_WINDOWS_TOTAL = Counter(
    "warehouse_pg_scheduler_duplicate_windows_total",
    "Decision inserts refused because the (schema, window) pair was already recorded",
)

SCAN_DURATION_SECONDS = Histogram(
    "warehouse_pg_scheduler_scan_duration_seconds",
    "Duration of the fleet-wide refresh scan",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0),
)

SCHEMAS_IN_SCOPE = Gauge(
    "warehouse_pg_scheduler_schemas_in_scope",
    "Schemas the scheduler currently manages state for",
    multiprocess_mode="livesum",
)

DUE_PER_TICK = Histogram(
    "warehouse_pg_scheduler_due_per_tick",
    "Number of due schemas claimed per leader tick",
    buckets=(0, 1, 5, 10, 25, 50, 100, 250, 500, 1000),
)

FIRE_LATENESS_SECONDS = Histogram(
    "warehouse_pg_scheduler_fire_lateness_seconds",
    "Seconds between a window's fire time and the tick that observed it",
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600),
)

MISSED_WINDOWS_TOTAL = Counter(
    "warehouse_pg_scheduler_missed_windows_total",
    "Fire windows that passed entirely between ticks (no decision recorded)",
)

TICKS_TOTAL = Counter(
    "warehouse_pg_scheduler_ticks_total",
    "Scheduler tick loop iterations",
    labelnames=["outcome"],
)


@frozen
class ShadowSchedulerConfig:
    database_url: str
    tick_interval_seconds: float = 60.0
    refresh_interval_seconds: float = 300.0
    claim_limit: int = 1000
    decision_retention_days: int = 30


class ShadowScheduler:
    def __init__(self, config: ShadowSchedulerConfig) -> None:
        self._config = config
        self._owner_token = str(uuid4())

    async def run(self, shutdown: asyncio.Event, health_reporter: Callable[[], None]) -> None:
        logger.info(
            "scheduler_starting",
            owner_token=self._owner_token,
            tick_interval=self._config.tick_interval_seconds,
            refresh_interval=self._config.refresh_interval_seconds,
            claim_limit=self._config.claim_limit,
            decision_retention_days=self._config.decision_retention_days,
        )
        while not shutdown.is_set():
            started = time.monotonic()
            try:
                await self._tick(health_reporter)
            except Exception:
                # No health report on a failed tick: a pod that cannot complete
                # ticks should trip the liveness timeout and restart.
                TICKS_TOTAL.labels(outcome="error").inc()
                logger.exception("scheduler_tick_failed")
            remainder = self._config.tick_interval_seconds - (time.monotonic() - started)
            if remainder > 0:
                try:
                    await asyncio.wait_for(shutdown.wait(), timeout=remainder)
                except TimeoutError:
                    pass
        logger.info("scheduler_stopped", owner_token=self._owner_token)

    async def _tick(self, health_reporter: Callable[[], None]) -> None:
        async with await psycopg.AsyncConnection.connect(self._config.database_url, autocommit=True) as conn:
            is_leader = await JobsTable.try_acquire_sentinel_slot(
                conn,
                lane=SCHEDULER_LANE,
                group_key=TICK_SLOT_KEY,
                owner_token=self._owner_token,
                ttl_seconds=self._config.tick_interval_seconds,
            )
            if not is_leader:
                TICKS_TOTAL.labels(outcome="follower").inc()
                health_reporter()
                return

            # Refresh before the due scan so a schema created or re-cadenced
            # moments ago is judged on this tick, not the next refresh.
            refresh_won = await JobsTable.try_acquire_sentinel_slot(
                conn,
                lane=SCHEDULER_LANE,
                group_key=REFRESH_SLOT_KEY,
                owner_token=self._owner_token,
                ttl_seconds=self._config.refresh_interval_seconds,
            )
            if refresh_won:
                await self._refresh(conn)

            now_epoch = int(time.time())
            async with conn.transaction():
                due = await SchedulerStateTable.claim_due(conn, limit=self._config.claim_limit)
                advances = []
                for row in due:
                    cadence = SchemaCadence(interval_seconds=row.interval_seconds, offset_seconds=row.offset_seconds)
                    advances.append((row.schema_id, datetime.fromtimestamp(next_due_after(now_epoch, cadence), tz=UTC)))
                await SchedulerStateTable.advance_states(conn, advances)

            DUE_PER_TICK.observe(len(due))
            result = await evaluate_due(due, now_epoch)
            inserted, refused = await SchedulerStateTable.insert_decisions(conn, list(result.records))

            out_of_scope = [r.schema_id for r in result.records if r.decision == DECISION_SKIP_OUT_OF_SCOPE]
            if out_of_scope:
                await SchedulerStateTable.delete_states(conn, out_of_scope)

            for record in result.records:
                FIRE_LATENESS_SECONDS.observe(record.late_seconds)
                if record.decision == DECISION_WOULD_FIRE:
                    WOULD_FIRE_TOTAL.inc()
                    logger.info(
                        "scheduler_would_fire",
                        schema_id=record.schema_id,
                        team_id=record.team_id,
                        due_at=record.due_at.isoformat(),
                        late_seconds=record.late_seconds,
                    )
                else:
                    SKIPS_TOTAL.labels(reason=SKIP_REASONS[record.decision]).inc()
                    logger.info(
                        "scheduler_skip",
                        schema_id=record.schema_id,
                        team_id=record.team_id,
                        due_at=record.due_at.isoformat(),
                        reason=SKIP_REASONS[record.decision],
                    )
            if refused:
                DUPLICATE_WINDOWS_TOTAL.inc(refused)
            if result.missed_windows:
                MISSED_WINDOWS_TOTAL.inc(result.missed_windows)

            TICKS_TOTAL.labels(outcome="leader").inc()
            logger.info(
                "scheduler_tick",
                due=len(due),
                decisions_inserted=inserted,
                duplicate_windows=refused,
                missed_windows=result.missed_windows,
                refreshed=refresh_won,
            )
            health_reporter()

    async def _refresh(self, conn: psycopg.AsyncConnection) -> None:
        started = time.monotonic()
        # DB-clock cutoff: upserts stamp refreshed_at with now() server-side, so
        # the stale-row delete must compare against the same clock.
        async with conn.cursor() as cur:
            await cur.execute("SELECT now()")
            row = await cur.fetchone()
            assert row is not None
            refresh_start = row[0]

        now_epoch = int(time.time())
        rows = await database_sync_to_async_pool(fetch_in_scope_schemas)()
        upserts: list[DueSchedule] = []
        for schema_id, team_id, interval, sync_time_of_day in rows:
            interval_seconds = int(interval.total_seconds())
            if interval_seconds <= 0:
                continue
            offset_seconds = schedule_offset(schema_id, interval, sync_time_of_day)
            cadence = SchemaCadence(interval_seconds=interval_seconds, offset_seconds=offset_seconds)
            upserts.append(
                DueSchedule(
                    schema_id=schema_id,
                    team_id=team_id,
                    interval_seconds=interval_seconds,
                    offset_seconds=offset_seconds,
                    # Only lands for new or re-cadenced rows; a schema is never
                    # due the first time the scheduler sees it.
                    next_due_at=datetime.fromtimestamp(next_due_after(now_epoch, cadence), tz=UTC),
                )
            )

        for start in range(0, len(upserts), UPSERT_BATCH_SIZE):
            await SchedulerStateTable.upsert_states(conn, upserts[start : start + UPSERT_BATCH_SIZE])
        deleted = await SchedulerStateTable.delete_states_not_refreshed_since(conn, refresh_start)
        pruned = await SchedulerStateTable.prune_decisions(conn, older_than_days=self._config.decision_retention_days)

        SCHEMAS_IN_SCOPE.set(len(upserts))
        SCAN_DURATION_SECONDS.observe(time.monotonic() - started)
        logger.info(
            "scheduler_refresh",
            in_scope=len(upserts),
            stale_deleted=deleted,
            decisions_pruned=pruned,
            duration_seconds=round(time.monotonic() - started, 3),
        )
