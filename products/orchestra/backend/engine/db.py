from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .types import Event, ExecutionStatus, Task


def _row_to_event(row: dict[str, Any]) -> Event:
    attrs = row["attributes"]
    if isinstance(attrs, str):
        attrs = json.loads(attrs)
    return Event(
        execution_id=row["execution_id"],
        run_id=row["run_id"],
        event_id=row["event_id"],
        event_type=row["event_type"],
        timestamp=row["timestamp"],
        attributes=attrs,
    )


def _row_to_task(row: dict[str, Any]) -> Task:
    raw_input = row["input"]
    if isinstance(raw_input, str):
        raw_input = json.loads(raw_input)
    return Task(
        task_id=row["task_id"],
        task_queue=row["task_queue"],
        task_type=row["task_type"],
        execution_id=row["execution_id"],
        run_id=row["run_id"],
        scheduled_event_id=row["scheduled_event_id"],
        step_type=row["step_type"],
        input=raw_input,
        visible_at=row["visible_at"],
        locked_by=row["locked_by"],
        locked_until=row["locked_until"],
        attempt=row["attempt"],
    )


class Database:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool

    @classmethod
    async def connect(cls, dsn: str, *, min_size: int = 1, max_size: int = 10) -> Database:
        pool = AsyncConnectionPool(conninfo=dsn, min_size=min_size, max_size=max_size, open=False)
        await pool.open()
        return cls(pool)

    async def close(self) -> None:
        await self.pool.close()

    async def lock_execution(self, conn: AsyncConnection[Any], execution_id: str, run_id: UUID) -> None:
        await conn.execute(
            "SELECT 1 FROM orchestra_execution WHERE execution_id=%s AND run_id=%s FOR UPDATE",
            (execution_id, run_id),
        )

    async def _next_event_id(self, conn: AsyncConnection[Any], execution_id: str, run_id: UUID) -> int:
        cur = await conn.execute(
            "SELECT coalesce(max(event_id), -1) + 1 AS next_id "
            "FROM orchestra_event WHERE execution_id=%s AND run_id=%s",
            (execution_id, run_id),
        )
        row = await cur.fetchone()
        assert row is not None
        return int(row[0])

    async def append_events(
        self,
        conn: AsyncConnection[Any],
        execution_id: str,
        run_id: UUID,
        events: list[tuple[str, dict[str, Any]]],
    ) -> list[int]:
        if not events:
            return []
        next_id = await self._next_event_id(conn, execution_id, run_id)
        assigned: list[int] = []
        for offset, (event_type, attrs) in enumerate(events):
            eid = next_id + offset
            assigned.append(eid)
            await conn.execute(
                "INSERT INTO orchestra_event (execution_id, run_id, event_id, event_type, attributes) "
                "VALUES (%s, %s, %s, %s, %s::jsonb)",
                (execution_id, run_id, eid, event_type, json.dumps(attrs)),
            )
        return assigned

    async def create_execution(
        self,
        conn: AsyncConnection[Any],
        *,
        execution_id: str,
        run_id: UUID,
        execution_type: str,
        step_queue: str,
        input: Any,
    ) -> None:
        await conn.execute(
            "INSERT INTO orchestra_execution (execution_id, run_id, execution_type, step_queue, input, status) "
            "VALUES (%s, %s, %s, %s, %s::jsonb, %s)",
            (execution_id, run_id, execution_type, step_queue, json.dumps(input), ExecutionStatus.RUNNING),
        )

    async def finish_execution(
        self,
        conn: AsyncConnection[Any],
        *,
        execution_id: str,
        run_id: UUID,
        status: str,
        result: Any = None,
        error: Any = None,
    ) -> None:
        await conn.execute(
            "UPDATE orchestra_execution SET status=%s, result=%s::jsonb, error=%s::jsonb, finished_at=now() "
            "WHERE execution_id=%s AND run_id=%s",
            (
                status,
                json.dumps(result) if result is not None else None,
                json.dumps(error) if error is not None else None,
                execution_id,
                run_id,
            ),
        )

    async def get_execution_step_queue(self, conn: AsyncConnection[Any], execution_id: str, run_id: UUID) -> str:
        cur = await conn.execute(
            "SELECT step_queue FROM orchestra_execution WHERE execution_id=%s AND run_id=%s",
            (execution_id, run_id),
        )
        row = await cur.fetchone()
        if row is None:
            raise LookupError(f"execution {execution_id}/{run_id} not found")
        return row[0]

    async def enqueue_task(
        self,
        conn: AsyncConnection[Any],
        *,
        task_queue: str,
        task_type: str,
        execution_id: str,
        run_id: UUID,
        scheduled_event_id: int | None = None,
        step_type: str | None = None,
        input: Any = None,
        visible_at: datetime | None = None,
    ) -> None:
        await conn.execute(
            "INSERT INTO orchestra_task "
            "(task_queue, task_type, execution_id, run_id, scheduled_event_id, step_type, input, visible_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, COALESCE(%s, now()))",
            (
                task_queue,
                task_type,
                execution_id,
                run_id,
                scheduled_event_id,
                step_type,
                json.dumps(input) if input is not None else None,
                visible_at,
            ),
        )

    async def poll_task(self, task_queue: str, worker_id: str, lease_seconds: int) -> Task | None:
        sql = (
            "UPDATE orchestra_task SET locked_by=%s, "
            "locked_until = now() + (%s || ' seconds')::interval "
            "WHERE task_id = ("
            "    SELECT task_id FROM orchestra_task "
            "    WHERE task_queue=%s AND visible_at <= now() AND locked_until IS NULL "
            "    ORDER BY visible_at "
            "    FOR UPDATE SKIP LOCKED LIMIT 1"
            ") RETURNING *"
        )
        async with self.pool.connection() as conn:
            conn.row_factory = dict_row
            cur = await conn.execute(sql, (worker_id, str(lease_seconds), task_queue))
            row = await cur.fetchone()
        return _row_to_task(row) if row else None

    async def complete_task(self, conn: AsyncConnection[Any], task_id: UUID) -> None:
        await conn.execute("DELETE FROM orchestra_task WHERE task_id=%s", (task_id,))

    async def release_task(self, task_id: UUID, retry_in: timedelta) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE orchestra_task SET locked_by=NULL, locked_until=NULL, "
                "visible_at = now() + (%s || ' seconds')::interval, attempt = attempt + 1 "
                "WHERE task_id=%s",
                (str(int(retry_in.total_seconds())), task_id),
            )

    async def load_history(self, execution_id: str, run_id: UUID) -> list[Event]:
        async with self.pool.connection() as conn:
            conn.row_factory = dict_row
            cur = await conn.execute(
                "SELECT execution_id, run_id, event_id, event_type, timestamp, attributes "
                "FROM orchestra_event WHERE execution_id=%s AND run_id=%s ORDER BY event_id",
                (execution_id, run_id),
            )
            rows = await cur.fetchall()
        return [_row_to_event(r) for r in rows]


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)
