import logging
from contextlib import suppress
from datetime import timedelta
from time import monotonic
from typing import Any

from django.conf import settings
from django.db import close_old_connections

import posthoganalytics
from asgiref.sync import async_to_sync, sync_to_async
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.scoped import scoped_temporal
from posthog.user_permissions import UserPermissions

from products.tasks.backend.logic.services.code_usage_gate import usage_limit_response
from products.tasks.backend.logic.services.workflow_dispatch import (
    WorkflowDispatchOptions,
    claim_dispatch,
    dispatch_exceeded_max_age,
    mark_accepted,
    mark_dead,
    new_dispatcher_instance_id,
    parse_create_payload,
    parse_restart_payload,
    release_claims,
    reschedule,
    resolve_ineligible,
)
from products.tasks.backend.metrics import (
    WORKFLOW_DISPATCH_ATTEMPT_TOTAL,
    WORKFLOW_DISPATCH_START_DURATION_SECONDS,
    WORKFLOW_DISPATCH_START_RPC_DURATION_SECONDS,
    observe_task_run_workflow_start,
)
from products.tasks.backend.models import Task, TaskRun, TaskWorkflowDispatch
from products.tasks.backend.temporal.client import (
    _capture_run_feature_flags,
    start_process_task_workflow,
    tag_startup_dispatch,
)
from products.tasks.backend.temporal.metrics import StepTimer
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskInput
from products.tasks.backend.visibility import task_control_q

logger = logging.getLogger(__name__)


def _user_can_dispatch(
    run: TaskRun, options: WorkflowDispatchOptions | None, *, require_task_control: bool = False
) -> bool:
    if options is not None and options.skip_user_check:
        return True
    user_id = options.user_id if options is not None else run.task.created_by_id
    if user_id is None:
        return False
    user = User.objects.filter(id=user_id, is_active=True).first()
    if user is None:
        return False
    if UserPermissions(user=user, team=run.task.team).current_team.effective_membership_level is None:
        return False
    return (
        not require_task_control
        or Task.objects.filter(task_control_q(user_id), id=run.task_id, team_id=run.team_id).exists()
    )


def _scheduled_run_usage_error(user: User, team_id: int) -> str | None:
    close_old_connections()
    try:
        response = usage_limit_response(user, team_id)
        return str(response.data["error"]) if response is not None else None
    finally:
        close_old_connections()


def _capture_run_feature_flags_in_worker_thread(run_id: str) -> dict[str, Any]:
    close_old_connections()
    try:
        return _capture_run_feature_flags(run_id)
    finally:
        close_old_connections()


async def dispatch_attempt_already_started(client: Client, dispatch: TaskWorkflowDispatch) -> bool:
    try:
        description = await client.get_workflow_handle(dispatch.workflow_id).describe(
            rpc_timeout=timedelta(seconds=settings.TASKS_DISPATCHER_RPC_TIMEOUT_SECONDS)
        )
    except RPCError as error:
        if error.status == RPCStatusCode.NOT_FOUND:
            return False
        raise
    if dispatch.dispatch_kind == TaskWorkflowDispatch.Kind.RESTART:
        return description.status == WorkflowExecutionStatus.RUNNING and description.start_time >= dispatch.enqueued_at
    return description.status in (
        WorkflowExecutionStatus.RUNNING,
        WorkflowExecutionStatus.COMPLETED,
        WorkflowExecutionStatus.CONTINUED_AS_NEW,
    )


@scoped_temporal(fresh=True, capture_exceptions=False)
@StepTimer("dispatch", status_tag="dispatch_status")
async def process_dispatch(client: Client, dispatch: TaskWorkflowDispatch, instance_id: str) -> None:
    run = await TaskRun.objects.select_related("task", "task__team").aget(id=dispatch.task_run_id)
    if run.status != TaskRun.Status.QUEUED:
        await sync_to_async(resolve_ineligible)(dispatch.id, instance_id)
        WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="resolved_ineligible").inc()
        return
    if dispatch_exceeded_max_age(dispatch, settings.TASKS_DISPATCHER_MAX_DISPATCH_AGE_SECONDS):
        await sync_to_async(mark_dead)(dispatch.id, instance_id, "Workflow dispatch exceeded maximum age", "max_age")
        WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="dead").inc()
        return
    tag_startup_dispatch(run)
    try:
        await Team.objects.aget(id=run.team_id)
        is_restart = dispatch.dispatch_kind == TaskWorkflowDispatch.Kind.RESTART
        is_scheduled_create = run.scheduled_at is not None and not is_restart
        if is_restart:
            requester_id, _ = parse_restart_payload(dispatch.payload)
            options = WorkflowDispatchOptions(user_id=requester_id)
        else:
            options = parse_create_payload(dispatch.payload)
        if (
            (is_restart or is_scheduled_create)
            and dispatch.attempt_count > 1
            and await dispatch_attempt_already_started(client, dispatch)
        ):
            await sync_to_async(mark_accepted)(dispatch.id, instance_id)
            posthoganalytics.tag("dispatch_status", "COMPLETED")
            WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="already_started").inc()
            return
        if not await sync_to_async(_user_can_dispatch)(run, options, require_task_control=is_scheduled_create):
            await sync_to_async(mark_dead)(
                dispatch.id,
                instance_id,
                "User no longer has task access" if is_scheduled_create else "User no longer has team access",
                "permission",
            )
            WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="dead").inc()
            return
        if is_scheduled_create:
            user = await User.objects.aget(id=options.user_id)
            usage_error = await sync_to_async(_scheduled_run_usage_error, thread_sensitive=False)(user, run.team_id)
            if usage_error is not None:
                await sync_to_async(mark_dead)(dispatch.id, instance_id, usage_error, "usage_limit")
                WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="dead").inc()
                return
        if is_restart:
            from products.tasks.backend.facade.streams import reset_task_run_stream  # noqa: PLC0415
            from products.tasks.backend.redis import run_uses_dedicated_stream  # noqa: PLC0415

            reset = await sync_to_async(reset_task_run_stream)(
                str(run.id), use_dedicated=run_uses_dedicated_stream(run.state)
            )
            if not reset:
                raise RuntimeError("Failed to reset task run event stream")
        run_state = await sync_to_async(_capture_run_feature_flags_in_worker_thread, thread_sensitive=False)(
            str(run.id)
        )
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
        try:
            await start_process_task_workflow(
                client,
                workflow_input,
                workflow_id=dispatch.workflow_id,
                id_reuse_policy=(
                    WorkflowIDReusePolicy.TERMINATE_IF_RUNNING
                    if is_restart
                    else WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
                ),
                run_state=run_state,
                rpc_timeout=timedelta(seconds=settings.TASKS_DISPATCHER_RPC_TIMEOUT_SECONDS),
            )
        finally:
            duration = monotonic() - started
            WORKFLOW_DISPATCH_START_DURATION_SECONDS.observe(duration)
            WORKFLOW_DISPATCH_START_RPC_DURATION_SECONDS.labels(kind=dispatch.dispatch_kind).observe(duration)
    except WorkflowAlreadyStartedError:
        if is_restart:
            await sync_to_async(reschedule)(dispatch.id, instance_id, "Restart workflow is already running")
            WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="rescheduled").inc()
            return
        await sync_to_async(mark_accepted)(dispatch.id, instance_id)
        posthoganalytics.tag("dispatch_status", "COMPLETED")
        WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="already_started").inc()
    except Exception as error:
        await sync_to_async(reschedule)(dispatch.id, instance_id, str(error))
        WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="rescheduled").inc()
    else:
        await sync_to_async(mark_accepted)(dispatch.id, instance_id)
        posthoganalytics.tag("dispatch_status", "COMPLETED")
        WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind=dispatch.dispatch_kind, outcome="accepted").inc()
        observe_task_run_workflow_start(run, outcome="started", reason="dispatcher")


async def _connect_and_process(dispatch: TaskWorkflowDispatch, instance_id: str) -> None:
    await process_dispatch(await async_connect(), dispatch, instance_id)


def start_dispatch_now(dispatch: TaskWorkflowDispatch) -> None:
    instance_id = new_dispatcher_instance_id()
    try:
        if not claim_dispatch(dispatch, instance_id, timedelta(seconds=settings.TASKS_DISPATCHER_LEASE_SECONDS)):
            return
        async_to_sync(_connect_and_process)(dispatch, instance_id)
    except Exception:
        logger.exception("workflow_dispatch_on_commit_failed", extra={"dispatch_id": str(dispatch.id)})
        with suppress(Exception):
            release_claims(instance_id)
