import os
import signal
import socket
import asyncio
import logging
import secrets
from datetime import timedelta
from functools import partial
from pathlib import Path
from time import monotonic

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import DatabaseError

from asgiref.sync import sync_to_async
from prometheus_client import start_http_server
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.common.client import async_connect
from posthog.user_permissions import UserPermissions

from products.tasks.backend.logic.services.workflow_dispatch import (
    WorkflowDispatchOptions,
    claim_dispatches,
    dispatch_exceeded_max_age,
    mark_accepted,
    mark_dead,
    parse_create_payload,
    parse_restart_payload,
    release_claims,
    renew_leases_in_worker_thread,
    reschedule,
    resolve_ineligible,
    sample_dispatch_metrics,
)
from products.tasks.backend.metrics import (
    WORKFLOW_DISPATCH_ATTEMPT_TOTAL,
    WORKFLOW_DISPATCH_START_DURATION_SECONDS,
    observe_task_run_workflow_start,
)
from products.tasks.backend.models import TaskRun, TaskWorkflowDispatch
from products.tasks.backend.temporal.client import _capture_run_feature_flags
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskInput

logger = logging.getLogger(__name__)


def _user_can_dispatch(run: TaskRun, options: WorkflowDispatchOptions | None) -> bool:
    if options is not None and options.skip_user_check:
        return True
    user_id = options.user_id if options is not None else run.task.created_by_id
    if user_id is None:
        return False
    user = User.objects.filter(id=user_id, is_active=True).first()
    if user is None:
        return False
    return UserPermissions(user=user, team=run.task.team).current_team.effective_membership_level is not None


async def restart_attempt_already_started(client: Client, dispatch: TaskWorkflowDispatch) -> bool:
    try:
        description = await client.get_workflow_handle(dispatch.workflow_id).describe(
            rpc_timeout=timedelta(seconds=settings.TASKS_DISPATCHER_RPC_TIMEOUT_SECONDS)
        )
    except RPCError as error:
        if error.status == RPCStatusCode.NOT_FOUND:
            return False
        raise
    return description.status == WorkflowExecutionStatus.RUNNING and description.start_time >= dispatch.enqueued_at


class Command(BaseCommand):
    help = "Dispatch queued task workflows from the durable outbox"

    def handle(self, *args: object, **options: object) -> None:
        start_http_server(8001)
        asyncio.run(self._run())

    async def _run(self) -> None:
        instance_id = f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(4)}"
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
            run = await TaskRun.objects.select_related("task", "task__team").aget(id=dispatch.task_run_id)
            if run.status != TaskRun.Status.QUEUED:
                await sync_to_async(resolve_ineligible)(dispatch.id, instance_id)
                WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="resolved_ineligible").inc()
                return
            if dispatch_exceeded_max_age(dispatch, settings.TASKS_DISPATCHER_MAX_DISPATCH_AGE_SECONDS):
                await sync_to_async(mark_dead)(
                    dispatch.id, instance_id, "Workflow dispatch exceeded maximum age", "max_age"
                )
                WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="dead").inc()
                return
            try:
                await Team.objects.aget(id=run.team_id)
                is_restart = dispatch.dispatch_kind == TaskWorkflowDispatch.Kind.RESTART
                if is_restart:
                    requester_id, _ = parse_restart_payload(dispatch.payload)
                    options = WorkflowDispatchOptions(user_id=requester_id)
                    if dispatch.attempt_count > 1 and await restart_attempt_already_started(client, dispatch):
                        await sync_to_async(mark_accepted)(dispatch.id, instance_id)
                        WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(
                            kind=dispatch.dispatch_kind, outcome="already_started"
                        ).inc()
                        return
                else:
                    options = parse_create_payload(dispatch.payload)
                if not await sync_to_async(_user_can_dispatch)(run, options):
                    await sync_to_async(mark_dead)(
                        dispatch.id, instance_id, "User no longer has team access", "permission"
                    )
                    WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="dead").inc()
                    return
                await sync_to_async(_capture_run_feature_flags, thread_sensitive=False)(str(run.id))
                if is_restart:
                    from products.tasks.backend.facade.streams import reset_task_run_stream  # noqa: PLC0415
                    from products.tasks.backend.redis import run_uses_dedicated_stream  # noqa: PLC0415

                    reset = await sync_to_async(reset_task_run_stream)(
                        str(run.id), use_dedicated=run_uses_dedicated_stream(run.state)
                    )
                    if not reset:
                        raise RuntimeError("Failed to reset task run event stream")
                workflow_input = ProcessTaskInput(
                    run_id=str(run.id),
                    create_pr=options.create_pr if options else True,
                    slack_thread_context=options.slack_thread_context if options else None,
                    posthog_mcp_scopes=options.posthog_mcp_scopes if options else "read_only",
                    prewarmed=options.prewarmed if options else False,
                    initial_message=options.initial_message if options else None,
                )
            except Team.DoesNotExist as error:
                await sync_to_async(mark_dead)(dispatch.id, instance_id, str(error), "permission")
                WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="dead").inc()
                return
            except (ValueError, KeyError, TypeError) as error:
                await sync_to_async(mark_dead)(dispatch.id, instance_id, str(error), "payload")
                WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="dead").inc()
                return
            except Exception as error:
                await sync_to_async(reschedule)(dispatch.id, instance_id, str(error))
                WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="rescheduled").inc()
                return
            started = monotonic()
            try:
                await client.start_workflow(
                    "process-task",
                    workflow_input,
                    id=dispatch.workflow_id,
                    id_reuse_policy=(
                        WorkflowIDReusePolicy.TERMINATE_IF_RUNNING
                        if is_restart
                        else WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
                    ),
                    task_queue=settings.TASKS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=3),
                    rpc_timeout=timedelta(seconds=settings.TASKS_DISPATCHER_RPC_TIMEOUT_SECONDS),
                )
            except WorkflowAlreadyStartedError:
                if is_restart:
                    await sync_to_async(reschedule)(dispatch.id, instance_id, "Restart workflow is already running")
                    WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="rescheduled").inc()
                    return
                await sync_to_async(mark_accepted)(dispatch.id, instance_id)
                WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="already_started").inc()
            except Exception as error:
                await sync_to_async(reschedule)(dispatch.id, instance_id, str(error))
                WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="rescheduled").inc()
            else:
                await sync_to_async(mark_accepted)(dispatch.id, instance_id)
                WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="accepted").inc()
                observe_task_run_workflow_start(run, outcome="started", reason="dispatcher")
            finally:
                WORKFLOW_DISPATCH_START_DURATION_SECONDS.observe(monotonic() - started)
