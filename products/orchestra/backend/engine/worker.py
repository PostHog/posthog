from __future__ import annotations

import socket
import asyncio
import logging
import traceback
from datetime import timedelta
from typing import Any
from uuid import uuid4

from .context import ExecutionContext
from .db import Database, utcnow
from .registry import get_execution, get_step
from .replay import build_replay_state
from .types import Event, EventType, ExecutionStatus, ScheduleStep, ScheduleTimer, StepFailed, Task, TaskType, _Suspend

logger = logging.getLogger("orchestra.worker")


class Worker:
    def __init__(
        self,
        db: Database,
        task_queue: str,
        *,
        lease_seconds: int = 30,
        concurrency: int = 4,
        poll_interval: float = 0.5,
        worker_id: str | None = None,
    ) -> None:
        self.db = db
        self.task_queue = task_queue
        self.lease_seconds = lease_seconds
        self.concurrency = concurrency
        self.poll_interval = poll_interval
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid4().hex[:8]}"
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        logger.info(
            "worker %s starting on queue %s (concurrency=%d)", self.worker_id, self.task_queue, self.concurrency
        )
        tasks = [asyncio.create_task(self._poll_loop(i)) for i in range(self.concurrency)]
        try:
            await self._stop.wait()
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _poll_loop(self, idx: int) -> None:
        while not self._stop.is_set():
            try:
                task = await self.db.poll_task(self.task_queue, self.worker_id, self.lease_seconds)
            except Exception:
                logger.exception("poller %d: failed to poll", idx)
                await asyncio.sleep(self.poll_interval)
                continue

            if task is None:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval)
                except TimeoutError:
                    pass
                continue

            try:
                await self._dispatch(task)
            except Exception:
                logger.exception("poller %d: task %s failed", idx, task.task_id)
                backoff = min(60, 2**task.attempt)
                try:
                    await self.db.release_task(task.task_id, timedelta(seconds=backoff))
                except Exception:
                    logger.exception("poller %d: failed to release task %s", idx, task.task_id)

    async def _dispatch(self, task: Task) -> None:
        match task.task_type:
            case TaskType.EXECUTION_TASK:
                await self._run_execution_task(task)
            case TaskType.STEP_TASK:
                await self._run_step_task(task)
            case TaskType.TIMER_TASK:
                await self._run_timer_task(task)
            case other:
                raise RuntimeError(f"unknown task_type {other!r}")

    async def _run_execution_task(self, task: Task) -> None:
        history = await self.db.load_history(task.execution_id, task.run_id)
        state = build_replay_state(history)

        if state.is_done:
            async with self.db.pool.connection() as conn:
                async with conn.transaction():
                    await self.db.complete_task(conn, task.task_id)
            return

        exec_type = _find_execution_type(history)
        exec_input = _find_execution_input(history)
        execution_fn = get_execution(exec_type)

        ctx = ExecutionContext(execution_id=task.execution_id, run_id=task.run_id, state=state)

        terminal_event: tuple[str, dict[str, Any]] | None = None
        try:
            result = await execution_fn(ctx, exec_input)
            terminal_event = (EventType.EXECUTION_COMPLETED, {"result": result})
        except _Suspend:
            pass
        except StepFailed as e:
            terminal_event = (EventType.EXECUTION_FAILED, {"error": {"type": "StepFailed", "message": str(e)}})
        except Exception as e:
            terminal_event = (
                EventType.EXECUTION_FAILED,
                {"error": {"type": type(e).__name__, "message": str(e), "traceback": traceback.format_exc()}},
            )

        async with self.db.pool.connection() as conn:
            async with conn.transaction():
                await self.db.lock_execution(conn, task.execution_id, task.run_id)

                if terminal_event is not None:
                    await self.db.append_events(conn, task.execution_id, task.run_id, task.team_id, [terminal_event])
                    status = (
                        ExecutionStatus.COMPLETED
                        if terminal_event[0] == EventType.EXECUTION_COMPLETED
                        else ExecutionStatus.FAILED
                    )
                    await self.db.finish_execution(
                        conn,
                        execution_id=task.execution_id,
                        run_id=task.run_id,
                        status=status,
                        result=terminal_event[1].get("result"),
                        error=terminal_event[1].get("error"),
                    )
                else:
                    new_events: list[tuple[str, dict[str, Any]]] = []
                    for cmd in ctx.commands:
                        if isinstance(cmd, ScheduleStep):
                            new_events.append(
                                (
                                    EventType.STEP_SCHEDULED,
                                    {"step_id": cmd.step_id, "step_type": cmd.step_type, "input": cmd.input},
                                )
                            )
                        elif isinstance(cmd, ScheduleTimer):
                            fire_at = utcnow() + timedelta(seconds=cmd.seconds)
                            new_events.append(
                                (
                                    EventType.TIMER_SCHEDULED,
                                    {
                                        "timer_id": cmd.timer_id,
                                        "seconds": cmd.seconds,
                                        "fire_at": fire_at.isoformat(),
                                    },
                                )
                            )
                    assigned_ids = await self.db.append_events(
                        conn, task.execution_id, task.run_id, task.team_id, new_events
                    )
                    for cmd, eid in zip(ctx.commands, assigned_ids):
                        if isinstance(cmd, ScheduleStep):
                            await self.db.enqueue_task(
                                conn,
                                task_queue=self.task_queue,
                                task_type=TaskType.STEP_TASK,
                                execution_id=task.execution_id,
                                run_id=task.run_id,
                                team_id=task.team_id,
                                scheduled_event_id=eid,
                                step_type=cmd.step_type,
                                input=cmd.input,
                            )
                        elif isinstance(cmd, ScheduleTimer):
                            await self.db.enqueue_task(
                                conn,
                                task_queue=self.task_queue,
                                task_type=TaskType.TIMER_TASK,
                                execution_id=task.execution_id,
                                run_id=task.run_id,
                                team_id=task.team_id,
                                scheduled_event_id=eid,
                                visible_at=utcnow() + timedelta(seconds=cmd.seconds),
                            )

                await self.db.complete_task(conn, task.task_id)

    async def _run_step_task(self, task: Task) -> None:
        assert task.step_type is not None
        step_fn = get_step(task.step_type)
        step_id = await self._lookup_attr_int(task, "step_id")

        try:
            result = await step_fn(task.input)
            outcome: tuple[str, dict[str, Any]] = (
                EventType.STEP_COMPLETED,
                {"step_id": step_id, "result": result},
            )
        except Exception as e:
            outcome = (
                EventType.STEP_FAILED,
                {"step_id": step_id, "error": {"type": type(e).__name__, "message": str(e)}},
            )

        async with self.db.pool.connection() as conn:
            async with conn.transaction():
                await self.db.lock_execution(conn, task.execution_id, task.run_id)
                await self.db.append_events(conn, task.execution_id, task.run_id, task.team_id, [outcome])
                await self.db.enqueue_task(
                    conn,
                    task_queue=self.task_queue,
                    task_type=TaskType.EXECUTION_TASK,
                    execution_id=task.execution_id,
                    run_id=task.run_id,
                    team_id=task.team_id,
                )
                await self.db.complete_task(conn, task.task_id)

    async def _run_timer_task(self, task: Task) -> None:
        timer_id = await self._lookup_attr_int(task, "timer_id")
        async with self.db.pool.connection() as conn:
            async with conn.transaction():
                await self.db.lock_execution(conn, task.execution_id, task.run_id)
                await self.db.append_events(
                    conn,
                    task.execution_id,
                    task.run_id,
                    task.team_id,
                    [(EventType.TIMER_FIRED, {"timer_id": timer_id})],
                )
                await self.db.enqueue_task(
                    conn,
                    task_queue=self.task_queue,
                    task_type=TaskType.EXECUTION_TASK,
                    execution_id=task.execution_id,
                    run_id=task.run_id,
                    team_id=task.team_id,
                )
                await self.db.complete_task(conn, task.task_id)

    async def _lookup_attr_int(self, task: Task, key: str) -> int:
        if task.scheduled_event_id is None:
            raise RuntimeError(f"task {task.task_id} has no scheduled_event_id")
        history = await self.db.load_history(task.execution_id, task.run_id)
        for ev in history:
            if ev.event_id == task.scheduled_event_id:
                return int(ev.attributes[key])
        raise RuntimeError(f"scheduled event {task.scheduled_event_id} not found in history")


def _find_execution_type(history: list[Event]) -> str:
    for ev in history:
        if ev.event_type == EventType.EXECUTION_STARTED:
            return ev.attributes["execution_type"]
    raise RuntimeError("EXECUTION_STARTED not found in history")


def _find_execution_input(history: list[Event]) -> Any:
    for ev in history:
        if ev.event_type == EventType.EXECUTION_STARTED:
            return ev.attributes.get("input")
    return None
