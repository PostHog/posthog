import signal
import asyncio
import logging
from datetime import timedelta
from functools import partial
from pathlib import Path
from time import monotonic

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import DatabaseError, close_old_connections

from asgiref.sync import sync_to_async
from prometheus_client import start_http_server
from temporalio.client import Client

from posthog.temporal.common.client import async_connect

from products.tasks.backend.logic.services.workflow_dispatch import (
    claim_dispatches,
    materialize_due_scheduled_task_runs,
    new_dispatcher_instance_id,
    release_claims,
    renew_leases_in_worker_thread,
    sample_dispatch_metrics,
)
from products.tasks.backend.logic.services.workflow_dispatch_processing import process_dispatch
from products.tasks.backend.metrics import WORKFLOW_DISPATCH_ATTEMPT_TOTAL
from products.tasks.backend.models import TaskWorkflowDispatch

logger = logging.getLogger(__name__)
SCHEDULED_RUN_MATERIALIZATION_BATCH_SIZE = 500


class Command(BaseCommand):
    help = "Dispatch queued task workflows from the durable outbox"

    def handle(self, *args: object, **options: object) -> None:
        start_http_server(8001)
        asyncio.run(self._run())

    async def _run(self) -> None:
        instance_id = new_dispatcher_instance_id()
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        client = await async_connect()
        Path("/tmp/dispatcher-ready").touch()
        semaphore = asyncio.Semaphore(settings.TASKS_DISPATCHER_CONCURRENCY)
        lease = timedelta(seconds=settings.TASKS_DISPATCHER_LEASE_SECONDS)
        in_flight: set[asyncio.Task[None]] = set()
        in_flight_ids: set[object] = set()
        renewer = asyncio.create_task(self._renew(instance_id, in_flight_ids, lease, stop))
        last_metrics_sample = 0.0
        try:
            while not stop.is_set():
                Path("/tmp/dispatcher-heartbeat").touch()
                try:
                    await sync_to_async(close_old_connections)()
                    await sync_to_async(materialize_due_scheduled_task_runs)(SCHEDULED_RUN_MATERIALIZATION_BATCH_SIZE)
                    if monotonic() - last_metrics_sample >= 15:
                        await sync_to_async(sample_dispatch_metrics)()
                        last_metrics_sample = monotonic()
                    available_capacity = settings.TASKS_DISPATCHER_CONCURRENCY - len(in_flight)
                    if available_capacity <= 0:
                        await asyncio.wait(in_flight, return_when=asyncio.FIRST_COMPLETED)
                        continue
                    rows = await sync_to_async(claim_dispatches)(
                        instance_id, min(settings.TASKS_DISPATCHER_BATCH_SIZE, available_capacity), lease
                    )
                except DatabaseError:
                    logger.exception("Task workflow dispatcher database poll failed")
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=settings.TASKS_DISPATCHER_POLL_INTERVAL_SECONDS)
                    except TimeoutError:
                        pass
                    continue
                if not rows:
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=settings.TASKS_DISPATCHER_POLL_INTERVAL_SECONDS)
                    except TimeoutError:
                        pass
                    continue
                for dispatch in rows:
                    in_flight_ids.add(dispatch.id)
                    task = asyncio.create_task(self._process(client, dispatch, instance_id, semaphore))
                    in_flight.add(task)
                    task.add_done_callback(partial(self._on_dispatch_done, in_flight, in_flight_ids, dispatch))
        finally:
            if in_flight:
                await asyncio.gather(*in_flight, return_exceptions=True)
            stop.set()
            await renewer
            await sync_to_async(release_claims)(instance_id)

    async def _renew(self, instance_id: str, dispatch_ids: set[object], lease: timedelta, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=20)
            except TimeoutError:
                if dispatch_ids:
                    try:
                        await sync_to_async(renew_leases_in_worker_thread, thread_sensitive=False)(
                            instance_id, list(dispatch_ids), lease
                        )
                    except Exception:
                        logger.exception("task_workflow_dispatch_lease_renewal_failed")

    @staticmethod
    def _on_dispatch_done(
        in_flight: set[asyncio.Task[None]],
        dispatch_ids: set[object],
        dispatch: TaskWorkflowDispatch,
        task: asyncio.Task[None],
    ) -> None:
        in_flight.discard(task)
        dispatch_ids.discard(dispatch.id)
        if task.cancelled():
            return
        error = task.exception()
        if error is None:
            return
        # An unhandled error in _process would otherwise surface only as an anonymous asyncio
        # "Task exception was never retrieved" warning, with no outcome metric. The claim stays
        # leased and is reclaimed by claim_dispatches once the lease expires.
        logger.error(
            "workflow_dispatch_worker_failed",
            exc_info=error,
            extra={"dispatch_id": str(dispatch.id), "task_run_id": str(dispatch.task_run_id)},
        )
        WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="failed").inc()

    async def _process(
        self, client: Client, dispatch: TaskWorkflowDispatch, instance_id: str, semaphore: asyncio.Semaphore
    ) -> None:
        async with semaphore:
            await process_dispatch(client, dispatch, instance_id)
