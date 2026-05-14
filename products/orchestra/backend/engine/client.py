from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from .db import Database
from .types import EventType, TaskType


class Client:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def start_execution(
        self,
        execution_type: str,
        input: Any = None,
        *,
        execution_id: str,
        team_id: int,
        step_queue: str = "default",
        run_id: UUID | None = None,
    ) -> UUID:
        run_id = run_id or uuid4()
        async with self.db.pool.connection() as conn:
            async with conn.transaction():
                await self.db.create_execution(
                    conn,
                    execution_id=execution_id,
                    run_id=run_id,
                    execution_type=execution_type,
                    step_queue=step_queue,
                    input=input,
                    team_id=team_id,
                )
                await self.db.lock_execution(conn, execution_id, run_id)
                await self.db.append_events(
                    conn,
                    execution_id,
                    run_id,
                    team_id,
                    [(EventType.EXECUTION_STARTED, {"execution_type": execution_type, "input": input})],
                )
                await self.db.enqueue_task(
                    conn,
                    task_queue=step_queue,
                    task_type=TaskType.EXECUTION_TASK,
                    execution_id=execution_id,
                    run_id=run_id,
                    team_id=team_id,
                )
        return run_id
