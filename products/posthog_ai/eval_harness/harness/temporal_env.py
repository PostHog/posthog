from __future__ import annotations

import os
import asyncio
import logging
import threading

from django.conf import settings

from temporalio.testing import WorkflowEnvironment

from posthog.temporal.common.client import async_connect
from posthog.temporal.common.worker import create_worker

from products.tasks.backend.facade.temporal import (
    ACTIVITIES as TASKS_ACTIVITIES,
    WORKFLOWS as TASKS_WORKFLOWS,
)

logger = logging.getLogger(__name__)


def temporal_client_target(env: WorkflowEnvironment) -> tuple[str, str]:
    config = env.client.config()
    service_client = config["service_client"]
    target_host = service_client.config.target_host
    host, port = target_host.rsplit(":", maxsplit=1)
    return host, port


async def start_temporal_env() -> WorkflowEnvironment:
    """Start an isolated Temporal dev server for sandboxed eval workflows.

    Awaited on the harness's main event loop, so eval workflows and the local
    dev server share one loop instead of the fixture's private throwaway loop.
    """
    # Hogli loads the dev OTLP exporter config, but the eval harness does not
    # start a collector. Disable trace export only while the Temporal child is
    # spawned, then restore the parent process environment immediately.
    previous_traces_exporter = os.environ.get("OTEL_TRACES_EXPORTER")
    os.environ["OTEL_TRACES_EXPORTER"] = "none"
    try:
        env = await WorkflowEnvironment.start_local(
            namespace=settings.TEMPORAL_NAMESPACE,
            ip="127.0.0.1",
            port=None,
            dev_server_log_level="warn",
        )
    finally:
        if previous_traces_exporter is None:
            os.environ.pop("OTEL_TRACES_EXPORTER", None)
        else:
            os.environ["OTEL_TRACES_EXPORTER"] = previous_traces_exporter
    host, port = temporal_client_target(env)
    logger.info("Sandboxed eval Temporal server ready at %s:%s namespace=%s", host, port, settings.TEMPORAL_NAMESPACE)
    return env


def temporal_task_queue() -> str:
    """Per-process task queue so eval workflows stay off any dev worker's queue."""
    return f"sandboxed-evals-tasks-{os.getpid()}"


async def terminate_stale_workflows() -> None:
    """Terminate any stale temporal workflows left over from previous runs.

    Without this, the in-process worker wastes time processing old workflows
    (creating sandboxes for runs that no longer exist in the test database),
    delaying the actual eval workflow by 30-60 seconds.
    """
    client = await async_connect()
    terminated = 0
    async for wf in client.list_workflows(f'TaskQueue="{settings.TASKS_TASK_QUEUE}"'):
        try:
            handle = client.get_workflow_handle(wf.id, run_id=wf.run_id)
            await handle.terminate(reason="eval harness cleanup")
            terminated += 1
        except Exception:
            pass
    if terminated:
        logger.info("Terminated %d stale temporal workflows", terminated)


class TemporalWorkerThread:
    """In-process temporal worker for the tasks queue, on its own thread + loop.

    Mirrors the dev worker (``manage.py start_temporal_worker``) using
    ``create_worker``. The worker runs on a private ``asyncio`` loop inside a
    daemon thread so it can poll Temporal without competing with the harness's
    main loop; DB access is unblocked (nothing blocks it in the harness) so
    temporal activities can use the Django ORM against the test database.
    """

    def __init__(self, *, max_concurrent_workflow_tasks: int = 100, max_concurrent_activities: int = 100) -> None:
        self._max_concurrent_workflow_tasks = max_concurrent_workflow_tasks
        self._max_concurrent_activities = max_concurrent_activities
        self._loop = asyncio.new_event_loop()
        self._stop_event = asyncio.Event()
        self._ready_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop.run_until_complete, args=(self._run(),), daemon=True)
        self._thread.start()

        if not self._ready_event.wait(timeout=30):
            raise RuntimeError(
                f"Temporal worker failed to start within 30s. "
                f"Is temporal running at {settings.TEMPORAL_HOST}:{settings.TEMPORAL_PORT}?"
            )

        logger.info("Eval temporal worker ready")

    async def _run(self) -> None:
        logger.info(
            "Starting eval temporal worker (%s:%s queue=%s)",
            settings.TEMPORAL_HOST,
            settings.TEMPORAL_PORT,
            settings.TASKS_TASK_QUEUE,
        )
        managed = await create_worker(
            host=settings.TEMPORAL_HOST,
            port=int(settings.TEMPORAL_PORT),
            metrics_port=0,
            namespace=settings.TEMPORAL_NAMESPACE,
            task_queue=settings.TASKS_TASK_QUEUE,
            workflows=TASKS_WORKFLOWS,
            activities=TASKS_ACTIVITIES,  # type: ignore[arg-type]
            max_concurrent_workflow_tasks=self._max_concurrent_workflow_tasks,
            max_concurrent_activities=self._max_concurrent_activities,
            enable_combined_metrics_server=False,
        )
        logger.info("Eval temporal worker created")
        self._ready_event.set()
        worker_task = asyncio.ensure_future(managed.run())
        await self._stop_event.wait()
        logger.info("Shutting down eval temporal worker")
        await managed.shutdown()
        worker_task.cancel()

    def stop(self) -> None:
        self._loop.call_soon_threadsafe(self._stop_event.set)
        if self._thread is not None:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                # The loop is still running the worker; closing it now would raise.
                # Leak it rather than risk a RuntimeError masking the real teardown.
                logger.warning("Eval temporal worker thread did not join in 10s; leaving its loop open")
                return
        self._loop.close()
