import asyncio
import logging
from typing import Any, Literal
from uuid import UUID

from django.utils import timezone as django_timezone

from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import sync_connect

from products.tasks.backend import push_dispatcher
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.process_task.activities.cleanup_sandbox import (
    CleanupSandboxInput,
    cleanup_sandbox_now,
    publish_run_stream_completion,
)
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

from . import (
    api as tasks_api,
    contracts,
)

logger = logging.getLogger(__name__)


def _signal_complete_task(
    run: TaskRun, status: str, error_message: str | None
) -> Literal["signaled", "workflow_gone", "unavailable"]:
    try:
        client = sync_connect()
        handle = client.get_workflow_handle(run.workflow_id)
        asyncio.run(handle.signal(ProcessTaskWorkflow.complete_task, args=[status, error_message]))
        return "signaled"
    except RPCError as error:
        if error.status == RPCStatusCode.NOT_FOUND:
            return "workflow_gone"
        logger.warning("Failed to signal workflow completion for task run %s: %s", run.id, error)
        return "unavailable"
    except Exception as error:
        logger.warning("Failed to signal workflow completion for task run %s: %s", run.id, error)
        return "unavailable"


def _interrupt_agent_turn(run: TaskRun, user_id: int | None, distinct_id: str | None) -> None:
    auth_token: str | None = None
    if user_id is not None and distinct_id:
        try:
            auth_token = tasks_api.create_sandbox_connection_token(run.id, user_id=user_id, distinct_id=distinct_id)
        except Exception:
            logger.warning("task_run_cancel_interrupt_auth_failed", extra={"run_id": str(run.id)})
    try:
        result = tasks_api.send_cancel(run.id, auth_token=auth_token)
        if not getattr(result, "success", False):
            logger.info("Agent turn interrupt failed for task run %s; continuing with cancel", run.id)
    except Exception as error:
        logger.warning("Agent turn interrupt errored for task run %s: %s", run.id, error)


def _cleanup_run_without_workflow(run: TaskRun) -> bool:
    sandbox_id = (run.state or {}).get("sandbox_id")
    if not isinstance(sandbox_id, str) or not sandbox_id:
        return True

    try:
        cleanup_sandbox_now(
            CleanupSandboxInput(
                sandbox_id=sandbox_id,
                run_id=str(run.id),
                stop_agent_server_on_cleanup=True,
                raise_on_error=True,
            )
        )
    except Exception:
        logger.warning("Failed to clean up sandbox for workflow-gone run %s", run.id, exc_info=True)
        return False
    return True


def _publish_cancel_fallback_completion(run: TaskRun) -> bool:
    if not (run.state or {}).get("cancel_fallback_cleanup_complete"):
        return True

    try:
        publish_run_stream_completion(str(run.id))
        TaskRun.update_state_atomic(run.id, updates={"cancel_fallback_cleanup_complete": False})
    except Exception:
        logger.warning("Failed to complete stream for workflow-gone run %s", run.id, exc_info=True)
        return False
    return True


def cancel_task_run(
    run_id: str | UUID,
    task_id: str | UUID,
    team_id: int,
    *,
    reason: str | None = None,
    source: str = "api",
    requested_by_user_id: int | None = None,
    requested_by_distinct_id: str | None = None,
) -> tuple[str, contracts.TaskRunDetailDTO | None]:
    run = tasks_api._get_visible_run(run_id, task_id, team_id)
    if run is None:
        return "not_found", None
    if run.is_terminal:
        if not _publish_cancel_fallback_completion(run):
            return "unavailable", tasks_api._task_run_detail_to_dto(run)
        return "already_terminal", tasks_api._task_run_detail_to_dto(run)
    if run.environment != TaskRun.Environment.CLOUD:
        return "not_cloud", tasks_api._task_run_detail_to_dto(run)

    status_at_request = run.status
    error_message = (reason or "").strip()[:500] or "Stopped by user"

    marker: dict[str, Any] = {
        "cancel_requested_at": django_timezone.now().isoformat(),
        "cancel_source": source,
    }
    if requested_by_user_id is not None:
        marker["cancel_requested_by_user_id"] = requested_by_user_id
    try:
        TaskRun.update_state_atomic(run.id, updates=marker)
    except Exception:
        logger.warning("Failed to record cancel request marker for task run %s", run.id, exc_info=True)

    _interrupt_agent_turn(run, requested_by_user_id, requested_by_distinct_id)

    signal_outcome = _signal_complete_task(run, TaskRun.Status.CANCELLED, error_message)
    if signal_outcome == "unavailable":
        return "unavailable", tasks_api._task_run_detail_to_dto(run)

    if signal_outcome == "workflow_gone":
        run = tasks_api._get_visible_run(run_id, task_id, team_id)
        if run is None:
            return "not_found", None
        if run.is_terminal:
            return "already_terminal", tasks_api._task_run_detail_to_dto(run)
        if not _cleanup_run_without_workflow(run):
            return "unavailable", tasks_api._task_run_detail_to_dto(run)
        TaskRun.update_state_atomic(run.id, updates={"cancel_fallback_cleanup_complete": True})
        dto = tasks_api.update_task_run(
            run.id,
            task_id,
            team_id,
            validated_data={"status": TaskRun.Status.CANCELLED, "error_message": error_message},
            only_if_non_terminal=True,
        )
        refreshed_run = tasks_api._get_visible_run(run_id, task_id, team_id)
        if refreshed_run is None:
            return "not_found", None
        if not _publish_cancel_fallback_completion(refreshed_run):
            return "unavailable", dto
    else:
        push_dispatcher.notify_task_run_cancelled(run)
        dto = tasks_api._task_run_detail_to_dto(run)

    run.capture_event(
        "task_run_cancel_requested",
        {
            "cancel_source": source,
            "cancel_reason": error_message,
            "requested_by_user_id": requested_by_user_id,
            "workflow_signal_outcome": signal_outcome,
            "status_at_request": status_at_request,
        },
    )
    return "accepted", dto
