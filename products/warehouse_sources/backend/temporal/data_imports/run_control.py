"""What an extraction run needs from the runtime that executes it.

The extraction body runs inside a Temporal activity or inside a queue consumer. Only the runtime
knows how to heartbeat, how to detect a shutdown, which attempt this is, and which ids the run has.
`RunControl` carries those values, so the extraction body does not call `activity.info()`.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable

from temporalio import activity

from posthog.dataclasses import frozen
from posthog.temporal.common.activity_context import current_workflow_id, current_workflow_run_id
from posthog.temporal.common.heartbeat import LivenessHeartbeater
from posthog.temporal.common.shutdown import ShutdownMonitor, WorkerShuttingDownError

from products.warehouse_sources.backend.temporal.data_imports.import_attempt import current_import_attempt


@frozen
class RunControl:
    # Called once per run. The run holds the returned context manager open while it extracts.
    heartbeat: Callable[[], contextlib.AbstractAsyncContextManager[object]]
    # Entered by the run. The pipeline checks it between batches.
    shutdown_monitor: ShutdownMonitor
    # 1-based. A value above 1 means an earlier attempt of the same job ran.
    attempt: int
    workflow_id: str | None
    workflow_run_id: str | None
    # True when the run holds the V3 pipeline lock under `workflow_run_id` and must confirm it
    # still holds it before it creates the job row.
    verify_v3_lock: bool
    # Thread-safe wait used by source code that blocks between requests. Returns early on shutdown.
    shutdown_wait: Callable[[float], object] | None = None


@contextlib.asynccontextmanager
async def no_heartbeat() -> AsyncIterator[None]:
    yield


def temporal_run_control() -> RunControl:
    """The control for a run inside a Temporal activity."""
    return RunControl(
        heartbeat=lambda: LivenessHeartbeater(factor=30),
        shutdown_monitor=ShutdownMonitor(),
        shutdown_wait=lambda timeout: activity.wait_for_worker_shutdown_sync(timeout=timeout),
        attempt=current_import_attempt(),
        workflow_id=current_workflow_id(),
        workflow_run_id=current_workflow_run_id(),
        verify_v3_lock=True,
    )


class EventShutdownMonitor(ShutdownMonitor):
    """A `ShutdownMonitor` that follows an `asyncio.Event` instead of the Temporal worker.

    The owner of the event sets it when the process must stop, for example on SIGTERM. The
    arguments after the event become the fields of the `WorkerShuttingDownError`, because there is
    no activity context to read them from.
    """

    def __init__(
        self,
        shutdown_event: asyncio.Event,
        *,
        activity_id: str,
        activity_type: str,
        task_queue: str,
        attempt: int,
        workflow_id: str | None,
        workflow_type: str | None,
    ) -> None:
        super().__init__()
        self._shutdown_event = shutdown_event
        self._activity_id = activity_id
        self._activity_type = activity_type
        self._task_queue = task_queue
        self._attempt = attempt
        self._workflow_id = workflow_id
        self._workflow_type = workflow_type

    def start(self) -> None:
        # The watcher only feeds `wait_for_worker_shutdown`. `is_worker_shutdown` reads the
        # injected event directly, so a check right after `start()` does not wait for a loop tick.
        async def monitor() -> None:
            await self._shutdown_event.wait()
            self._is_shutdown_event.set()
            self._is_shutdown_event_sync.set()

        self._monitor_shutdown_task = asyncio.create_task(monitor())

    def start_sync(self) -> None:
        # No thread is necessary: `is_worker_shutdown` reads the event, and reading `is_set()` is
        # safe from any thread.
        return None

    def stop_sync(self) -> None:
        return None

    def is_worker_shutdown(self) -> bool:
        return self._shutdown_event.is_set() or super().is_worker_shutdown()

    def raise_if_is_worker_shutdown(self) -> None:
        if self.is_worker_shutdown():
            self.logger.debug("Worker is shutting down.")
            raise WorkerShuttingDownError(
                self._activity_id,
                self._activity_type,
                self._task_queue,
                self._attempt,
                self._workflow_id,
                self._workflow_type,
            )
