import uuid
import asyncio
import logging
from typing import TYPE_CHECKING, Any, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone as django_timezone

import posthoganalytics
from asgiref.sync import sync_to_async
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.models.team.team import Team
from posthog.temporal.common.client import async_connect, sync_connect
from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.constants import SANDBOX_EVENT_INGEST_FEATURE_FLAG
from products.tasks.backend.metrics import observe_task_run_workflow_start
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskInput
from products.tasks.backend.temporal.slack_relay.activities import RelaySlackMessageInput

if TYPE_CHECKING:
    from products.slack_app.backend.slack_thread import SlackThreadContext

logger = logging.getLogger(__name__)

_PRE_START_STATUSES: tuple[str, ...] = (TaskRun.Status.NOT_STARTED, TaskRun.Status.QUEUED)


def _normalize_slack_context(slack_thread_context: Optional[Any]) -> Optional[dict[str, Any]]:
    """Convert slack_thread_context to dict if needed."""
    if slack_thread_context is None:
        return None
    if hasattr(slack_thread_context, "to_dict"):
        return slack_thread_context.to_dict()
    return slack_thread_context


def _terminalize_unstarted_task_run(run_id: str, error_message: str) -> bool:
    try:
        with transaction.atomic():
            task_run = TaskRun.objects.select_for_update().get(id=run_id)
            if task_run.status not in _PRE_START_STATUSES:
                logger.info(
                    "task_processing_start_failure_not_terminalized",
                    extra={
                        "run_id": run_id,
                        "status": task_run.status,
                    },
                )
                return False

            task_run.status = TaskRun.Status.FAILED
            task_run.error_message = error_message
            task_run.completed_at = django_timezone.now()
            task_run.save(update_fields=["status", "error_message", "completed_at"])
    except TaskRun.DoesNotExist:
        logger.warning("task_processing_start_failure_task_run_missing", extra={"run_id": run_id})
        return False

    task_run.publish_stream_state_event()
    task_run.capture_event(
        "task_run_failed",
        {
            "error_message": error_message[:500],
            "duration_seconds": task_run._duration_seconds(),
        },
    )
    return True


async def _terminalize_unstarted_task_run_async(run_id: str, error_message: str) -> bool:
    return await sync_to_async(_terminalize_unstarted_task_run)(run_id, error_message)


def _get_task_run_for_metrics(run_id: str) -> TaskRun | None:
    try:
        return TaskRun.objects.select_related("task").get(id=run_id)
    except Exception:
        return None


def _capture_sandbox_event_ingest_flag(run_id: str) -> None:
    try:
        task_run = TaskRun.objects.select_related("task__created_by", "task__team").get(id=run_id)
    except Exception:
        logger.exception("sandbox_event_ingest_capture_run_missing", extra={"run_id": run_id})
        return

    state = task_run.state or {}
    if isinstance(state.get("sandbox_event_ingest_enabled"), bool):
        return

    task = task_run.task
    organization_id = str(task.team.organization_id)
    distinct_id = (
        task.created_by.distinct_id if task.created_by and task.created_by.distinct_id else "process_task_workflow"
    )

    try:
        enabled = bool(
            posthoganalytics.feature_enabled(
                SANDBOX_EVENT_INGEST_FEATURE_FLAG,
                distinct_id=distinct_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        logger.warning(
            "sandbox_event_ingest_capture_flag_failed",
            extra={"run_id": run_id, "task_id": str(task.id), "error": str(e)},
        )
        enabled = False

    def _set_sandbox_event_ingest_flag(latest_state: dict[str, Any]) -> None:
        if not isinstance(latest_state.get("sandbox_event_ingest_enabled"), bool):
            latest_state["sandbox_event_ingest_enabled"] = enabled

    captured_state = TaskRun.mutate_state_atomic(task_run.id, _set_sandbox_event_ingest_flag)
    captured_enabled = captured_state.get("sandbox_event_ingest_enabled", enabled)
    logger.info(
        "sandbox_event_ingest_captured",
        extra={"run_id": run_id, "task_id": str(task.id), "sandbox_event_ingest_enabled": captured_enabled},
    )


async def _aget_task_run_for_metrics(run_id: str) -> TaskRun | None:
    try:
        return await TaskRun.objects.select_related("task").aget(id=run_id)
    except Exception:
        return None


async def execute_task_processing_workflow_async(
    task_id: str,
    run_id: str,
    team_id: int,
    user_id: Optional[int] = None,
    create_pr: bool = True,
    slack_thread_context: Optional[Any] = None,
    skip_user_check: bool = False,
    posthog_mcp_scopes: PosthogMcpScopes = "read_only",
    prewarmed: bool = False,
) -> None:
    """
    Start the task processing workflow asynchronously. Fire-and-forget.
    Use this from async contexts (e.g., within Temporal activities).
    """
    logger.info(
        "execute_task_processing_workflow_async_called",
        extra={"task_id": task_id, "run_id": run_id},
    )
    # Keep the metrics lookups inside the try: if either raises, the except clauses must still
    # terminalize the run. When they ran before the try, an exception here aborted the dispatch
    # without marking the run FAILED, orphaning it in QUEUED until the 24h janitor swept it.
    # observe_task_run_workflow_start tolerates a None task_run.
    task_run_for_metrics: TaskRun | None = None
    try:
        task_run_for_metrics = await _aget_task_run_for_metrics(run_id)
        observe_task_run_workflow_start(task_run_for_metrics, outcome="attempted", reason="requested")
        await Team.objects.select_related("organization").aget(id=team_id)
        await sync_to_async(_capture_sandbox_event_ingest_flag)(run_id)

        workflow_id = TaskRun.get_workflow_id(task_id, run_id)
        slack_context_dict = _normalize_slack_context(slack_thread_context)

        workflow_input = ProcessTaskInput(
            run_id=run_id,
            create_pr=create_pr,
            slack_thread_context=slack_context_dict,
            posthog_mcp_scopes=posthog_mcp_scopes,
            prewarmed=prewarmed,
        )

        logger.info(
            "task_processing_starting_workflow",
            extra={"workflow_id": workflow_id, "task_id": task_id, "run_id": run_id},
        )

        client = await async_connect()
        await client.start_workflow(
            "process-task",
            workflow_input,
            id=workflow_id,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            task_queue=settings.TASKS_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        logger.info("task_processing_workflow_started", extra={"task_id": task_id, "run_id": run_id})
        observe_task_run_workflow_start(task_run_for_metrics, outcome="started", reason="accepted")

    except Team.DoesNotExist as e:
        observe_task_run_workflow_start(task_run_for_metrics, outcome="failed", reason="permission_validation")
        logger.exception(
            "task_processing_permission_validation_failed",
            extra={"task_id": task_id, "run_id": run_id, "error": str(e)},
        )
        await _terminalize_unstarted_task_run_async(
            run_id,
            f"Failed to start task workflow: permission validation failed: {e}",
        )
    except Exception as e:
        observe_task_run_workflow_start(task_run_for_metrics, outcome="failed", reason="temporal_start")
        logger.exception(
            "task_processing_workflow_start_failed",
            extra={"task_id": task_id, "run_id": run_id, "error": str(e)},
        )
        await _terminalize_unstarted_task_run_async(
            run_id,
            f"Failed to start task workflow: {e}",
        )


def execute_task_processing_workflow(
    task_id: str,
    run_id: str,
    team_id: int,
    user_id: Optional[int] = None,
    create_pr: bool = True,
    slack_thread_context: Optional["SlackThreadContext"] = None,
    skip_user_check: bool = False,
    posthog_mcp_scopes: PosthogMcpScopes = "read_only",
    prewarmed: bool = False,
) -> None:
    """
    Start the task processing workflow synchronously. Fire-and-forget.
    Use this from sync contexts (e.g., API endpoints).
    """
    # Metrics lookups stay inside the try so a failure here can't bypass terminalization and
    # leave the run orphaned in QUEUED (see the async variant above).
    task_run_for_metrics: TaskRun | None = None
    try:
        task_run_for_metrics = _get_task_run_for_metrics(run_id)
        observe_task_run_workflow_start(task_run_for_metrics, outcome="attempted", reason="requested")
        logger.info(
            "execute_task_processing_workflow_called",
            extra={"task_id": task_id, "run_id": run_id, "team_id": team_id, "user_id": user_id},
        )

        Team.objects.get(id=team_id)
        _capture_sandbox_event_ingest_flag(run_id)

        workflow_id = TaskRun.get_workflow_id(task_id, run_id)
        slack_context_dict = _normalize_slack_context(slack_thread_context)

        workflow_input = ProcessTaskInput(
            run_id=run_id,
            create_pr=create_pr,
            slack_thread_context=slack_context_dict,
            posthog_mcp_scopes=posthog_mcp_scopes,
            prewarmed=prewarmed,
        )

        logger.info(
            "task_processing_connecting_temporal",
            extra={"task_id": task_id, "task_queue": settings.TASKS_TASK_QUEUE},
        )

        client = sync_connect()

        logger.info(
            "task_processing_temporal_connected",
            extra={"workflow_id": workflow_id, "task_id": task_id, "run_id": run_id},
        )

        asyncio.run(
            client.start_workflow(
                "process-task",
                workflow_input,
                id=workflow_id,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                task_queue=settings.TASKS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        )

        logger.info("task_processing_workflow_started", extra={"task_id": task_id, "run_id": run_id})
        observe_task_run_workflow_start(task_run_for_metrics, outcome="started", reason="accepted")

    except Team.DoesNotExist as e:
        observe_task_run_workflow_start(task_run_for_metrics, outcome="failed", reason="permission_validation")
        logger.exception(
            "task_processing_permission_validation_failed",
            extra={"task_id": task_id, "run_id": run_id, "error": str(e)},
        )
        _terminalize_unstarted_task_run(
            run_id,
            f"Failed to start task workflow: permission validation failed: {e}",
        )
    except Exception as e:
        observe_task_run_workflow_start(task_run_for_metrics, outcome="failed", reason="temporal_start")
        logger.exception(
            "task_processing_workflow_start_failed",
            extra={"task_id": task_id, "run_id": run_id, "error": str(e)},
        )
        _terminalize_unstarted_task_run(
            run_id,
            f"Failed to start task workflow: {e}",
        )


def _resolve_mcp_scopes(task_run: TaskRun) -> PosthogMcpScopes:
    """Mirror ``_trigger_task_processing_workflow``: full scopes unless the run_source is scoped down."""
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — avoid an import cycle
        RunSource,
        parse_run_state,
    )

    run_source = parse_run_state(task_run.state).run_source
    return "full" if run_source in (None, RunSource.MANUAL, RunSource.SIGNAL_REPORT) else "read_only"


def redispatch_orphaned_task_run(run_id: str) -> str:
    """Re-dispatch a run stuck in QUEUED whose create-time on_commit dispatch never fired.

    Idempotent and recover-only: ``ALLOW_DUPLICATE_FAILED_ONLY`` starts a workflow only when
    none is live for this run, so a run that is already running (row not yet flipped to
    IN_PROGRESS) is left untouched. Never terminalizes the run — a transient Temporal failure
    just retries on the next sweep, and the 24h killer remains the only path that fails a run.

    Returns an outcome for metrics/logs: ``recovered`` (workflow started), ``already_running``
    (a workflow already exists), ``left_queue`` (row is no longer QUEUED), ``skipped_prewarmed``
    (owned by the prewarmed reaper), ``skipped_local`` (desktop-driven run, nothing to recover),
    ``error`` (transient).
    """
    from temporalio.exceptions import WorkflowAlreadyStartedError  # noqa: PLC0415 — keep temporalio off the import path

    task_run = (
        TaskRun.objects.select_related("task")  # nosemgrep: celery-task-team-scope-audit
        .filter(id=run_id, status=TaskRun.Status.QUEUED)
        .first()
    )
    if task_run is None:
        return "left_queue"

    # Local (desktop) runs idle in QUEUED while the user's local agent drives them — there is no
    # lost dispatch to recover. Starting a cloud workflow here would hijack the live session: the
    # sandbox boots without the repo ever being cloned, burns its retries, and marks the user's
    # run FAILED. The sweep already filters these out (cloud_only); this guards direct callers.
    if task_run.environment == TaskRun.Environment.LOCAL:
        return "skipped_local"

    # Prewarmed runs idle in QUEUED awaiting the user's first message; the dedicated prewarmed
    # reaper *kills* them if never activated. Recovering one would boot an agent with no prompt
    # (and re-dispatching without the prewarmed flag would change its boot behaviour), so skip.
    if isinstance(task_run.state, dict) and task_run.state.get("prewarmed"):
        return "skipped_prewarmed"

    task = task_run.task
    task_id = str(task.id)
    workflow_id = TaskRun.get_workflow_id(task_id, run_id)
    # create_and_run persists these on the row; the bootstrap/start path does not, so fall back to
    # deriving mcp scopes from run_source exactly as _trigger_task_processing_workflow does.
    pending = task_run.state.get("pending_dispatch") if isinstance(task_run.state, dict) else None
    dispatch_params = pending if isinstance(pending, dict) else {}
    workflow_input = ProcessTaskInput(
        run_id=run_id,
        create_pr=dispatch_params.get("create_pr", True),
        slack_thread_context=dispatch_params.get("slack_thread_context"),
        posthog_mcp_scopes=dispatch_params.get("posthog_mcp_scopes") or _resolve_mcp_scopes(task_run),
    )

    observe_task_run_workflow_start(task_run, outcome="attempted", reason="reconcile")
    _capture_sandbox_event_ingest_flag(run_id)
    try:
        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                "process-task",
                workflow_input,
                id=workflow_id,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                task_queue=settings.TASKS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        )
    except WorkflowAlreadyStartedError:
        observe_task_run_workflow_start(task_run, outcome="blocked", reason="reconcile_already_running")
        return "already_running"
    except Exception as e:
        observe_task_run_workflow_start(task_run, outcome="failed", reason="reconcile_error")
        logger.warning(
            "task_run_reconcile_dispatch_failed",
            extra={"run_id": run_id, "task_id": task_id, "error": str(e)},
        )
        return "error"

    observe_task_run_workflow_start(task_run, outcome="started", reason="reconcile")
    logger.info("task_run_reconcile_dispatch_started", extra={"run_id": run_id, "task_id": task_id})
    return "recovered"


def resume_task_in_cloud_workflow(run_id: str, workflow_id: str) -> None:
    _capture_sandbox_event_ingest_flag(run_id)
    client = sync_connect()
    asyncio.run(
        client.start_workflow(
            "process-task",
            ProcessTaskInput(run_id=run_id),
            id=workflow_id,
            # TERMINATE_IF_RUNNING closes any prior workflow under this ID
            # atomically before starting the new one, avoiding the async-cancel
            # race where a best-effort cancel signal hasn't landed yet.
            id_reuse_policy=WorkflowIDReusePolicy.TERMINATE_IF_RUNNING,
            task_queue=settings.TASKS_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
    )


def signal_task_followup_message(workflow_id: str, message: str | None, artifact_ids: list[str]) -> None:
    client = sync_connect()
    handle = client.get_workflow_handle(workflow_id)
    asyncio.run(handle.signal("send_followup_message", args=[message, artifact_ids]))


def signal_agent_text_delta(workflow_id: str, text: str) -> None:
    """Push text into the live agent-design plan-block stream for a running task."""
    client = sync_connect()
    handle = client.get_workflow_handle(workflow_id)
    asyncio.run(handle.signal("agent_text_delta", text))


def signal_task_permission_response(
    workflow_id: str,
    *,
    request_id: str,
    option_id: str,
    actor_user_id: int,
    actor_slack_user_id: str | None = None,
    is_denial: bool = False,
    denial_message: str | None = None,
    broker_reason: str | None = None,
) -> None:
    client = sync_connect()
    handle = client.get_workflow_handle(workflow_id)
    payload: dict[str, Any] = {
        "request_id": request_id,
        "option_id": option_id,
        "actor_user_id": actor_user_id,
        "actor_slack_user_id": actor_slack_user_id,
        "is_denial": is_denial,
        "denial_message": denial_message,
        "broker_reason": broker_reason,
    }
    asyncio.run(handle.signal("send_permission_response", arg=payload))


def execute_posthog_code_agent_relay_workflow(
    run_id: str,
    text: str,
    relay_id: str | None = None,
    user_message_ts: str | None = None,
    delete_progress: bool = True,
    reaction_emoji: str | None = None,
) -> str:
    relay_id = relay_id or str(uuid.uuid4())
    workflow_id = f"posthog-code-agent-relay-{run_id}-{relay_id}"

    client = sync_connect()
    asyncio.run(
        client.start_workflow(
            "posthog-code-agent-relay",
            RelaySlackMessageInput(
                run_id=run_id,
                relay_id=relay_id,
                text=text,
                user_message_ts=user_message_ts,
                delete_progress=delete_progress,
                reaction_emoji=reaction_emoji,
            ),
            id=workflow_id,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            task_queue=settings.TASKS_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
    )
    return relay_id
