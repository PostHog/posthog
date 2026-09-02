"""Scheduler state: SQL and row types for the shadow scheduler's tables.

``queueschedulerstate`` holds one row per in-scope schema with its cadence and
the next epoch-aligned due time; ``queueschedulerdecision`` is the append-only
record of what the scheduler would have done at each window. Both tables are
small (one row per schema, decisions pruned on a retention window), so unlike
the job tables they are not partitioned. All SQL lives here (the ``JobsTable``
idiom); the tick loop drives it from ``warehouse_sources``' shadow runner.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from posthog.dataclasses import frozen

SCHEDULER_STATE_TABLE = "queueschedulerstate"
SCHEDULER_DECISION_TABLE = "queueschedulerdecision"


@frozen
class DueSchedule:
    """One scheduler-state row: a schema's cadence and its next due time."""

    schema_id: str
    team_id: int
    interval_seconds: int
    offset_seconds: int
    next_due_at: datetime


@frozen
class DecisionRecord:
    """One shadow decision for a schema's fire window."""

    team_id: int
    schema_id: str
    window_boundary: datetime
    due_at: datetime
    decision: str
    interval_seconds: int
    late_seconds: float


_UPSERT_STATE_SQL = f"""
    INSERT INTO {SCHEDULER_STATE_TABLE} (
        schema_id, team_id, interval_seconds, offset_seconds, next_due_at, refreshed_at, updated_at
    )
    VALUES (
        %(schema_id)s, %(team_id)s, %(interval_seconds)s, %(offset_seconds)s, %(next_due_at)s, now(), now()
    )
    ON CONFLICT (schema_id) DO UPDATE SET
        team_id = excluded.team_id,
        -- A cadence change re-anchors the schedule; an unchanged cadence keeps
        -- the stored due time so refreshes never move a pending fire.
        next_due_at = CASE
            WHEN ({SCHEDULER_STATE_TABLE}.interval_seconds, {SCHEDULER_STATE_TABLE}.offset_seconds)
                 IS DISTINCT FROM (excluded.interval_seconds, excluded.offset_seconds)
                THEN excluded.next_due_at
            ELSE {SCHEDULER_STATE_TABLE}.next_due_at
        END,
        interval_seconds = excluded.interval_seconds,
        offset_seconds = excluded.offset_seconds,
        refreshed_at = now(),
        updated_at = now()
"""

_INSERT_DECISION_SQL = f"""
    INSERT INTO {SCHEDULER_DECISION_TABLE} (
        team_id, schema_id, window_boundary, due_at, decision, interval_seconds, late_seconds
    )
    VALUES (
        %(team_id)s, %(schema_id)s, %(window_boundary)s, %(due_at)s, %(decision)s,
        %(interval_seconds)s, %(late_seconds)s
    )
    ON CONFLICT (schema_id, window_boundary) DO NOTHING
"""


class SchedulerStateTable:
    """Raw SQL over the scheduler tables (the ``JobsTable`` idiom)."""

    @staticmethod
    async def upsert_states(
        conn: psycopg.AsyncConnection[Any],
        rows: list[DueSchedule],
    ) -> None:
        """Refresh the fleet's cadence rows. ``next_due_at`` only lands for new
        rows and for rows whose (interval, offset) changed."""
        if not rows:
            return
        async with conn.cursor() as cur:
            await cur.executemany(
                _UPSERT_STATE_SQL,
                [
                    {
                        "schema_id": row.schema_id,
                        "team_id": row.team_id,
                        "interval_seconds": row.interval_seconds,
                        "offset_seconds": row.offset_seconds,
                        "next_due_at": row.next_due_at,
                    }
                    for row in rows
                ],
            )

    @staticmethod
    async def delete_states_not_refreshed_since(
        conn: psycopg.AsyncConnection[Any],
        cutoff: datetime,
    ) -> int:
        """Drop rows the latest refresh did not touch (schemas that left scope)."""
        async with conn.cursor() as cur:
            await cur.execute(
                f"DELETE FROM {SCHEDULER_STATE_TABLE} WHERE refreshed_at < %(cutoff)s",
                {"cutoff": cutoff},
            )
            return cur.rowcount

    @staticmethod
    async def claim_due(
        conn: psycopg.AsyncConnection[Any],
        *,
        limit: int,
    ) -> list[DueSchedule]:
        """Lock and return the due rows. Call inside a transaction and advance
        the same rows with :meth:`advance_states` before it commits, so a
        concurrent claimer (SKIP LOCKED) never double-observes a window."""
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                SELECT schema_id, team_id, interval_seconds, offset_seconds, next_due_at
                FROM {SCHEDULER_STATE_TABLE}
                WHERE next_due_at <= now()
                ORDER BY next_due_at
                LIMIT %(limit)s
                FOR UPDATE SKIP LOCKED
                """,
                {"limit": limit},
            )
            rows = await cur.fetchall()
        return [DueSchedule(**row) for row in rows]

    @staticmethod
    async def advance_states(
        conn: psycopg.AsyncConnection[Any],
        rows: list[tuple[str, datetime]],
    ) -> None:
        """Advance claimed rows to their next due time; pair with :meth:`claim_due`."""
        if not rows:
            return
        async with conn.cursor() as cur:
            await cur.executemany(
                f"""
                UPDATE {SCHEDULER_STATE_TABLE}
                SET next_due_at = %(next_due_at)s, updated_at = now()
                WHERE schema_id = %(schema_id)s
                """,
                [{"schema_id": schema_id, "next_due_at": next_due_at} for schema_id, next_due_at in rows],
            )

    @staticmethod
    async def delete_states(
        conn: psycopg.AsyncConnection[Any],
        schema_ids: list[str],
    ) -> int:
        """Drop specific state rows (schemas the due scan found out of scope)."""
        if not schema_ids:
            return 0
        async with conn.cursor() as cur:
            await cur.execute(
                f"DELETE FROM {SCHEDULER_STATE_TABLE} WHERE schema_id = ANY(%(schema_ids)s)",
                {"schema_ids": schema_ids},
            )
            return cur.rowcount

    @staticmethod
    async def insert_decisions(
        conn: psycopg.AsyncConnection[Any],
        records: list[DecisionRecord],
    ) -> tuple[int, int]:
        """Record decisions; returns (inserted, refused). A refusal means the
        (schema_id, window_boundary) pair was already recorded, which in a
        single-flighted fleet indicates a duplicate-window bug worth a metric."""
        if not records:
            return (0, 0)
        async with conn.cursor() as cur:
            await cur.executemany(
                _INSERT_DECISION_SQL,
                [
                    {
                        "team_id": record.team_id,
                        "schema_id": record.schema_id,
                        "window_boundary": record.window_boundary,
                        "due_at": record.due_at,
                        "decision": record.decision,
                        "interval_seconds": record.interval_seconds,
                        "late_seconds": record.late_seconds,
                    }
                    for record in records
                ],
            )
            inserted = max(cur.rowcount, 0)
        return (inserted, len(records) - inserted)

    @staticmethod
    async def prune_decisions(
        conn: psycopg.AsyncConnection[Any],
        *,
        older_than_days: int,
    ) -> int:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                DELETE FROM {SCHEDULER_DECISION_TABLE}
                WHERE observed_at < now() - make_interval(days => %(days)s)
                """,
                {"days": older_than_days},
            )
            return cur.rowcount

    @staticmethod
    def fetch_would_fires(
        conn: psycopg.Connection[Any],
        since: datetime,
    ) -> list[DecisionRecord]:
        """Read the would-fire decisions for the shadow report (sync caller)."""
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT team_id, schema_id, window_boundary, due_at, decision, interval_seconds, late_seconds
                FROM {SCHEDULER_DECISION_TABLE}
                WHERE decision = 'would_fire' AND due_at >= %(since)s
                ORDER BY due_at
                """,
                {"since": since},
            )
            rows = cur.fetchall()
        return [DecisionRecord(**row) for row in rows]
