import asyncio
import logging
from typing import Any, Literal
from uuid import UUID

from django.db import transaction
from django.utils import timezone as django_timezone

from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import sync_connect

from products.tasks.backend import push_dispatcher
from products.tasks.backend.metrics import observe_cancel_enqueue_failed
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

# How long a signaled cancellation gets to be applied by its own workflow before the
# verification task terminalizes the run itself. Sits above the slowest healthy cancel
# path (turn interrupt, resume snapshot, sandbox teardown) so the normal case is never raced.
CANCEL_VERIFICATION_DELAY_SECONDS = 5 * 60


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


def _terminate_workflow(run: TaskRun, reason: str) -> Literal["terminated", "workflow_gone", "unavailable"]:
    """Hard-stop the run's workflow.

    Terminate, not cancel: a cancel is delivered as an event the workflow has to pick up and act
    on, which is exactly what a wedged event loop cannot do. Terminate is applied server-side and
    needs nothing from the workflow, at the cost of skipping its cleanup - hence the sandbox
    teardown the caller runs afterwards.
    """
    try:
        client = sync_connect()
        handle = client.get_workflow_handle(run.workflow_id)
        # Keyword, not positional: positional args on terminate() are stored as termination
        # details, and the history event's reason field would be left empty.
        asyncio.run(handle.terminate(reason=reason))
        return "terminated"
    except RPCError as error:
        # NOT_FOUND covers both "no such workflow" and "already closed"; either way nothing is running.
        if error.status == RPCStatusCode.NOT_FOUND:
            return "workflow_gone"
        logger.warning("Failed to terminate workflow for task run %s: %s", run.id, error)
        return "unavailable"
    except Exception as error:
        logger.warning("Failed to terminate workflow for task run %s: %s", run.id, error)
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


def _cleanup_run_without_workflow(run: TaskRun) -> None:
    """Tear down the run's sandbox when no workflow will do it. Best-effort by contract.

    An orphaned sandbox still dies on its own TTL, whereas a run left non-terminal never
    recovers, so callers must carry on to the CANCELLED write regardless of the outcome here.
    """
    sandbox_id = (run.state or {}).get("sandbox_id")
    if not isinstance(sandbox_id, str) or not sandbox_id:
        return

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


def _finalize_cancel_without_workflow(
    run: TaskRun,
    run_id: str | UUID,
    task_id: str | UUID,
    team_id: int,
    error_message: str,
) -> tuple[contracts.TaskRunDetailDTO | None, Literal["accepted", "not_found", "unavailable"]]:
    """Terminalize a run in the DB when no workflow is going to do it.

    Sandbox teardown, the CANCELLED write, then the stream close. ``unavailable`` means the run
    is cancelled but its stream is still open; the marker survives so a retry finishes the job.
    """
    _cleanup_run_without_workflow(run)
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
        return dto, "not_found"
    if not _publish_cancel_fallback_completion(refreshed_run):
        return dto, "unavailable"
    return dto, "accepted"


def _schedule_cancel_verification(run: TaskRun, task_id: str | UUID, team_id: int, error_message: str) -> None:
    """Arm the deadline for a cancellation the workflow may never apply.

    ``complete_task`` is a signal: reaching the workflow's queue is all a ``signaled`` outcome
    proves, and the caller gets its 202 straight away. A workflow whose event loop is wedged
    never applies it and nothing else re-checks the run, so the request would be lost silently.
    """
    from products.tasks.backend.facade.tasks import (  # noqa: PLC0415 - the celery module imports back into the facade
        verify_task_run_cancelled_task,
    )

    run_id = str(run.id)

    def _enqueue() -> None:
        try:
            verify_task_run_cancelled_task.apply_async(
                args=[run_id, str(task_id), team_id, error_message],
                countdown=CANCEL_VERIFICATION_DELAY_SECONDS,
            )
        except Exception:
            # Raising here cannot help: the cancellation was already signaled and committed, and
            # this callback runs past the point where the caller could be told to retry. Count it
            # so a broker outage that disarms the deadline is visible rather than silent.
            observe_cancel_enqueue_failed(kind="verification")
            logger.warning("Failed to schedule cancel verification for task run %s", run_id, exc_info=True)

    transaction.on_commit(_enqueue)


def force_terminalize_cancelled_run(
    run_id: str | UUID,
    task_id: str | UUID,
    team_id: int,
    *,
    reason: str,
) -> Literal["not_needed", "terminalized", "unavailable"]:
    """Terminalize a run whose workflow was signaled to cancel but never acted on it.

    A healthy workflow applies the signal well inside the verification delay, so the expected
    outcome is ``not_needed`` on an already-terminal run. ``unavailable`` means work is still
    outstanding - an unreachable workflow, or a run that is CANCELLED with its stream still open -
    so the caller must re-attempt.
    """
    run = tasks_api._get_visible_run(run_id, task_id, team_id)
    if run is None or run.environment != TaskRun.Environment.CLOUD:
        return "not_needed"

    if run.is_terminal:
        # Whoever wrote the terminal status owns everything except the stream close, which is the
        # one step that can be left outstanding and is re-attemptable: its marker on the run says
        # whether it is, and the publish is a no-op when it is not.
        return "not_needed" if _publish_cancel_fallback_completion(run) else "unavailable"

    terminate_outcome = _terminate_workflow(run, reason)
    if terminate_outcome == "unavailable":
        # The workflow may still be alive and unaware. Writing CANCELLED here would leave it
        # executing against a sandbox we just tore down, and a retry would then take the
        # already-terminal branch above and never revisit the divergence.
        logger.warning(
            "Leaving task run %s non-terminal: its workflow could not be terminated",
            run.id,
        )
        return "unavailable"

    # The workflow is dead either way now, so the run has to end up terminal. `not_found` means
    # the run went away and there is nothing left to finish; `unavailable` means it is CANCELLED
    # but its stream is still open, which the already-terminal branch above retries.
    _, finalize_outcome = _finalize_cancel_without_workflow(run, run_id, task_id, team_id, reason)
    logger.warning(
        "Force-terminalized task run %s after an unapplied cancellation (terminate=%s, finalize=%s)",
        run.id,
        terminate_outcome,
        finalize_outcome,
    )
    return "unavailable" if finalize_outcome == "unavailable" else "terminalized"


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
        dto, finalize_outcome = _finalize_cancel_without_workflow(run, run_id, task_id, team_id, error_message)
        if finalize_outcome != "accepted":
            return finalize_outcome, dto
    else:
        push_dispatcher.notify_task_run_cancelled(run)
        dto = tasks_api._task_run_detail_to_dto(run)
        _schedule_cancel_verification(run, task_id, team_id, error_message)

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
