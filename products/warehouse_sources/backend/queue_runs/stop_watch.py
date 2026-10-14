"""Stop a queue run when the consumer shuts down or when someone cancels the run.

No Temporal cancel reaches a queue run, so the watch polls the job row instead. A cancel writes a
terminal status to the job first, so a terminal status on a running extraction means "stop".
"""

from __future__ import annotations

import enum
import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class StopReason(enum.StrEnum):
    SHUTDOWN = "shutdown"
    CANCELLED = "cancelled"


class RunStopWatch:
    """Watch one extraction task, and stop it when the consumer shuts down or the run is cancelled.

    A stop first sets `stop_event`. The extraction checks that event between batches (through its
    `ShutdownMonitor`) and ends with `WorkerShuttingDownError`. Some runs never check it, for
    example a full refresh. So after a grace period the watch cancels the task.
    """

    def __init__(
        self,
        *,
        shutdown_event: asyncio.Event,
        is_run_cancelled: Callable[[], Awaitable[bool]],
        probe_interval_seconds: float,
        shutdown_grace_seconds: float,
        cancel_grace_seconds: float,
    ) -> None:
        self._shutdown_event = shutdown_event
        self._is_run_cancelled = is_run_cancelled
        self._probe_interval_seconds = probe_interval_seconds
        self._shutdown_grace_seconds = shutdown_grace_seconds
        self._cancel_grace_seconds = cancel_grace_seconds
        self.stop_event = asyncio.Event()
        self.reason: StopReason | None = None
        # True when the watch cancelled the task because it did not stop in time.
        self.cancelled_work = False

    async def watch(self, work: asyncio.Task[Any]) -> None:
        while not work.done():
            shutdown_wait = asyncio.ensure_future(self._shutdown_event.wait())
            try:
                await asyncio.wait(
                    {shutdown_wait, work}, timeout=self._probe_interval_seconds, return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                shutdown_wait.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await shutdown_wait
            if work.done():
                return
            if self._shutdown_event.is_set():
                await self._stop(StopReason.SHUTDOWN, self._shutdown_grace_seconds, work)
                return
            try:
                cancelled = await self._is_run_cancelled()
            except Exception as e:
                # A failed probe must not stop a healthy run. The next probe tries again.
                logger.warning("extract_cancel_probe_failed", error=str(e))
                continue
            if cancelled:
                await self._stop(StopReason.CANCELLED, self._cancel_grace_seconds, work)
                return

    async def _stop(self, reason: StopReason, grace_seconds: float, work: asyncio.Task[Any]) -> None:
        self.reason = reason
        self.stop_event.set()
        logger.info("extract_run_stopping", reason=reason.value, grace_seconds=grace_seconds)
        await asyncio.wait({work}, timeout=grace_seconds)
        if not work.done():
            self.cancelled_work = True
            work.cancel()
