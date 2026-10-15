"""Scheduler state: SQL and row types for scheduler tables.

``queueschedulerstate`` holds one row per schedule with its cadence and
the next epoch-aligned due time; ``queueschedulerdecision`` is the append-only
record of what the scheduler would have done at each window. Both tables are
small (one row per schedule, decisions pruned on a retention window), so unlike
the job tables they are not partitioned. All SQL lives here (the ``JobsTable``
idiom); callers drive the tick loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

SCHEDULER_STATE_TABLE = "queueschedulerstate"
SCHEDULER_DECISION_TABLE = "queueschedulerdecision"


@dataclass(frozen=True, kw_only=True, slots=True)
class DueSchedule:
    """One scheduler-state row: a schedule's cadence and its next due time."""

    kind: str
    schedule_key: str
    team_id: int
    interval_seconds: int
    offset_seconds: int
    next_due_at: datetime


@dataclass(frozen=True, kw_only=True, slots=True)
class DecisionRecord:
    """One decision for a schedule's fire window."""

    team_id: int
    kind: str
    schedule_key: str
    window_boundary: datetime
    due_at: datetime
    decision: str
    interval_seconds: int
    late_seconds: float


_UPSERT_STATE_SQL = f"""
    INSERT INTO {SCHEDULER_STATE_TABLE} (
        kind, schedule_key, team_id, interval_seconds, offset_seconds, next_due_at, refreshed_at, updated_at
    )
    SELECT kind, schedule_key, team_id, interval_seconds, offset_seconds, next_due_at, now(), now()
    FROM unnest(
        %(kinds)s::text[],
        %(schedule_keys)s::text[],
        %(team_ids)s::bigint[],
        %(intervals)s::bigint[],
        %(offsets)s::integer[],
        %(due_times)s::timestamptz[]
    ) AS rows(kind, schedule_key, team_id, interval_seconds, offset_seconds, next_due_at)
    ON CONFLICT (kind, schedule_key) DO UPDATE SET
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

_INSERT_DECISIONS_SQL = f"""
    WITH input AS (
        SELECT *
        FROM unnest(
            %(team_ids)s::bigint[],
            %(kinds)s::text[],
            %(schedule_keys)s::text[],
            %(window_boundaries)s::timestamptz[],
            %(due_times)s::timestamptz[],
            %(decisions)s::text[],
            %(intervals)s::bigint[],
            %(lateness)s::double precision[]
        ) WITH ORDINALITY AS rows(
            team_id, kind, schedule_key, window_boundary, due_at, decision,
            interval_seconds, late_seconds, record_index
        )
    ), deduplicated AS (
        SELECT DISTINCT ON (kind, schedule_key, due_at) *
        FROM input
        ORDER BY kind, schedule_key, due_at, record_index
    ), inserted AS (
        INSERT INTO {SCHEDULER_DECISION_TABLE} (
            team_id, kind, schedule_key, window_boundary, due_at, decision, interval_seconds, late_seconds
        )
        SELECT team_id, kind, schedule_key, window_boundary, due_at, decision, interval_seconds, late_seconds
        FROM deduplicated
        ON CONFLICT (kind, schedule_key, due_at) DO NOTHING
        RETURNING kind, schedule_key, due_at
    )
    SELECT deduplicated.record_index
    FROM deduplicated
    INNER JOIN inserted USING (kind, schedule_key, due_at)
    ORDER BY deduplicated.record_index
"""


class SchedulerStateTable:
    """Raw SQL over the scheduler tables (the ``JobsTable`` idiom)."""

    @staticmethod
    async def upsert_states(
        conn: psycopg.AsyncConnection[Any],
        rows: list[DueSchedule],
    ) -> None:
        """Refresh the fleet's cadence rows in one statement. ``next_due_at``
        only lands for new rows and for rows whose (interval, offset) changed.

        Each (kind, schedule_key) must appear at most once in ``rows``: Postgres
        refuses an upsert that touches the same row twice.
        """
        if not rows:
            return
        async with conn.cursor() as cur:
            await cur.execute(
                _UPSERT_STATE_SQL,
                {
                    "kinds": [row.kind for row in rows],
                    "schedule_keys": [row.schedule_key for row in rows],
                    "team_ids": [row.team_id for row in rows],
                    "intervals": [row.interval_seconds for row in rows],
                    "offsets": [row.offset_seconds for row in rows],
                    "due_times": [row.next_due_at for row in rows],
                },
            )

    @staticmethod
    async def delete_states_not_refreshed_since(
        conn: psycopg.AsyncConnection[Any],
        kind: str,
        cutoff: datetime,
    ) -> int:
        """Drop rows the latest refresh did not touch."""
        async with conn.cursor() as cur:
            await cur.execute(
                f"DELETE FROM {SCHEDULER_STATE_TABLE} WHERE kind = %(kind)s AND refreshed_at < %(cutoff)s",
                {"kind": kind, "cutoff": cutoff},
            )
            return cur.rowcount

    @staticmethod
    async def claim_due(
        conn: psycopg.AsyncConnection[Any],
        *,
        kind: str,
        limit: int,
    ) -> list[DueSchedule]:
        """Lock and return the due rows. Call inside a transaction and advance
        the same rows with :meth:`advance_states` before it commits, so a
        concurrent claimer (SKIP LOCKED) never double-observes a window."""
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                SELECT kind, schedule_key, team_id, interval_seconds, offset_seconds, next_due_at
                FROM {SCHEDULER_STATE_TABLE}
                WHERE kind = %(kind)s AND next_due_at <= now()
                ORDER BY next_due_at
                LIMIT %(limit)s
                FOR UPDATE SKIP LOCKED
                """,
                {"kind": kind, "limit": limit},
            )
            rows = await cur.fetchall()
        return [DueSchedule(**row) for row in rows]

    @staticmethod
    async def advance_states(
        conn: psycopg.AsyncConnection[Any],
        rows: list[tuple[DueSchedule, datetime]],
    ) -> None:
        """Advance claimed rows to their next due time; pair with :meth:`claim_due`."""
        if not rows:
            return
        async with conn.cursor() as cur:
            await cur.executemany(
                f"""
                UPDATE {SCHEDULER_STATE_TABLE}
                SET next_due_at = %(next_due_at)s, updated_at = now()
                WHERE kind = %(kind)s AND schedule_key = %(schedule_key)s
                """,
                [
                    {"kind": row.kind, "schedule_key": row.schedule_key, "next_due_at": next_due_at}
                    for row, next_due_at in rows
                ],
            )

    @staticmethod
    async def delete_states(
        conn: psycopg.AsyncConnection[Any],
        kind: str,
        schedule_keys: list[str],
    ) -> int:
        """Drop specific state rows that left scope."""
        if not schedule_keys:
            return 0
        async with conn.cursor() as cur:
            await cur.execute(
                f"DELETE FROM {SCHEDULER_STATE_TABLE} WHERE kind = %(kind)s AND schedule_key = ANY(%(schedule_keys)s)",
                {"kind": kind, "schedule_keys": schedule_keys},
            )
            return cur.rowcount

    @staticmethod
    async def insert_decisions(
        conn: psycopg.AsyncConnection[Any],
        records: list[DecisionRecord],
    ) -> tuple[list[DecisionRecord], int]:
        """Record decisions and return (inserted records, refused count).

        A refusal means the (kind, schedule_key, due_at) tuple was already recorded,
        which in a single-flighted fleet indicates a duplicate-window bug
        worth a metric.
        """
        if not records:
            return ([], 0)
        async with conn.cursor() as cur:
            await cur.execute(
                _INSERT_DECISIONS_SQL,
                {
                    "team_ids": [record.team_id for record in records],
                    "kinds": [record.kind for record in records],
                    "schedule_keys": [record.schedule_key for record in records],
                    "window_boundaries": [record.window_boundary for record in records],
                    "due_times": [record.due_at for record in records],
                    "decisions": [record.decision for record in records],
                    "intervals": [record.interval_seconds for record in records],
                    "lateness": [record.late_seconds for record in records],
                },
            )
            inserted_indexes = [row[0] - 1 for row in await cur.fetchall()]
        inserted = [records[index] for index in inserted_indexes]
        return (inserted, len(records) - len(inserted))

    @staticmethod
    async def prune_decisions(
        conn: psycopg.AsyncConnection[Any],
        *,
        kind: str,
        older_than_days: int,
    ) -> int:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                DELETE FROM {SCHEDULER_DECISION_TABLE}
                WHERE kind = %(kind)s AND observed_at < now() - make_interval(days => %(days)s)
                """,
                {"kind": kind, "days": older_than_days},
            )
            return cur.rowcount

    @staticmethod
    def fetch_would_fires(
        conn: psycopg.Connection[Any],
        kind: str,
        since: datetime,
    ) -> list[DecisionRecord]:
        """Read the would-fire decisions for one kind."""
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT team_id, kind, schedule_key, window_boundary, due_at, decision, interval_seconds, late_seconds
                FROM {SCHEDULER_DECISION_TABLE}
                WHERE kind = %(kind)s AND decision = 'would_fire' AND due_at >= %(since)s
                ORDER BY due_at
                """,
                {"kind": kind, "since": since},
            )
            rows = cur.fetchall()
        return [DecisionRecord(**row) for row in rows]
