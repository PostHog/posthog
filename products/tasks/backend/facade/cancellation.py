import asyncio
import logging
from typing import Any, Literal
from uuid import UUID

from django.db import transaction
from django.utils import timezone as django_timezone

from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import sync_connect

from products.tasks.backend import push_dispatcher
from products.tasks.backend.logic.stream.redis_stream import (
    TASK_RUN_STREAM_INITIAL_GENERATION,
    get_task_run_stream_generation,
)
from products.tasks.backend.models import TaskRun
from products.tasks.backend.redis import run_uses_dedicated_stream
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
) -> Literal["signaled", "workflow_gone", "not_sent", "delivery_unknown"]:
    try:
        client = sync_connect()
    except Exception as error:
        logger.warning("Failed to connect to Temporal for task run %s: %s", run.id, error)
        return "not_sent"
    try:
        handle = client.get_workflow_handle(run.workflow_id)
        asyncio.run(handle.signal(ProcessTaskWorkflow.complete_task, args=[status, error_message]))
        return "signaled"
    except RPCError as error:
        if error.status == RPCStatusCode.NOT_FOUND:
            return "workflow_gone"
        logger.warning("Failed to signal workflow completion for task run %s: %s", run.id, error)
        return "delivery_unknown"
    except Exception as error:
        logger.warning("Failed to signal workflow completion for task run %s: %s", run.id, error)
        return "delivery_unknown"


def _record_cancel_marker(run_id: UUID, marker: dict[str, Any]) -> bool:
    fenced_before = False

    def record(state: dict[str, Any]) -> None:
        nonlocal fenced_before
        fenced_before = bool(state.get("cancel_requested_at"))
        state.update(marker)

    TaskRun.mutate_state_atomic(run_id, record)
    return not fenced_before


def _withdraw_cancel_marker(run_id: UUID, marker: dict[str, Any]) -> dict[str, Any]:
    def withdraw(state: dict[str, Any]) -> None:
        if state.get("cancel_requested_at") != marker["cancel_requested_at"]:
            return
        for key in marker:
            state.pop(key, None)

    return TaskRun.mutate_state_atomic(run_id, withdraw)


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
        publish_run_stream_completion(
            str(run.id), stream_generation=(run.state or {}).get("cancel_fallback_stream_generation")
        )
        TaskRun.update_state_atomic(run.id, updates={"cancel_fallback_cleanup_complete": False})
    except Exception:
        logger.warning("Failed to complete stream for cancelled run %s", run.id, exc_info=True)
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
    only_if_awaiting_first_message: bool = False,
) -> tuple[str, contracts.TaskRunDetailDTO | None]:
    """Cancel a run. Returns the outcome and the run as it now stands.

    ``only_if_awaiting_first_message`` makes this a warm hand-back rather than a cancel: the run is
    stopped only while it is still idling for its first message. One warm Run is shared by every
    composer holding the same selection (``_find_idling_warm_run`` dedupes on the selection, not on the
    composer), so without this fence a composer that releases its lease after another one submitted
    would stop the run that submit activated.
    """
    run = tasks_api._get_visible_run(run_id, task_id, team_id)
    if run is None:
        return "not_found", None
    if run.is_terminal:
        if not _publish_cancel_fallback_completion(run):
            return "unavailable", tasks_api._task_run_detail_to_dto(run)
        return "already_terminal", tasks_api._task_run_detail_to_dto(run)
    if only_if_awaiting_first_message and not (run.state or {}).get("await_user_message"):
        return "already_activated", tasks_api._task_run_detail_to_dto(run)
    if run.environment != TaskRun.Environment.CLOUD:
        return "not_cloud", tasks_api._task_run_detail_to_dto(run)

    status_at_request = run.status
    error_message = (reason or "").strip()[:500] or "Stopped by user"

    def capture_cancel_request(task_run: TaskRun, signal_outcome: str) -> None:
        task_run.capture_event(
            "task_run_cancel_requested",
            {
                "cancel_source": source,
                "cancel_reason": error_message,
                "requested_by_user_id": requested_by_user_id,
                "workflow_signal_outcome": signal_outcome,
                "status_at_request": status_at_request,
            },
        )

    marker: dict[str, Any] = {
        "cancel_requested_at": django_timezone.now().isoformat(),
        "cancel_source": source,
    }
    if requested_by_user_id is not None:
        marker["cancel_requested_by_user_id"] = requested_by_user_id
    owns_marker = False
    try:
        if only_if_awaiting_first_message:
            with transaction.atomic():
                run = TaskRun.objects.select_for_update().get(id=run.id, task_id=task_id, team_id=team_id)
                can_release = (
                    not run.is_terminal
                    and bool((run.state or {}).get("await_user_message"))
                    and not (run.state or {}).get("warm_activation_started")
                )
                if can_release:
                    owns_marker = not (run.state or {}).get("cancel_requested_at")
                    run.state = {**(run.state or {}), **marker}
                    run.save(update_fields=["state", "updated_at"])
            if not can_release:
                return "already_activated", tasks_api._task_run_detail_to_dto(run)
        else:
            owns_marker = _record_cancel_marker(run.id, marker)
    except Exception:
        logger.warning("Failed to record cancel request marker for task run %s", run.id, exc_info=True)
        if only_if_awaiting_first_message:
            return "unavailable", tasks_api._task_run_detail_to_dto(run)

    if run.scheduled_at is not None and run.status == TaskRun.Status.NOT_STARTED:
        dto = tasks_api.update_task_run(
            run.id,
            task_id,
            team_id,
            validated_data={"status": TaskRun.Status.CANCELLED, "error_message": error_message},
            only_if_not_started=True,
        )
        if dto is not None:
            capture_cancel_request(run, "not_needed")
            run.refresh_from_db(fields=["state"])
            if not _publish_cancel_fallback_completion(run):
                return "unavailable", dto
            return "accepted", dto
        run = tasks_api._get_visible_run(run_id, task_id, team_id)
        if run is None:
            return "not_found", None
        if run.is_terminal:
            if not _publish_cancel_fallback_completion(run):
                return "unavailable", tasks_api._task_run_detail_to_dto(run)
            return "already_terminal", tasks_api._task_run_detail_to_dto(run)

    _interrupt_agent_turn(run, requested_by_user_id, requested_by_distinct_id)

    signal_outcome = _signal_complete_task(run, TaskRun.Status.CANCELLED, error_message)
    if signal_outcome == "not_sent" and owns_marker:
        try:
            run.state = _withdraw_cancel_marker(run.id, marker)
        except Exception:
            logger.warning("Failed to withdraw cancel request marker for task run %s", run.id, exc_info=True)
    if signal_outcome in ("not_sent", "delivery_unknown"):
        return "unavailable", tasks_api._task_run_detail_to_dto(run)

    if signal_outcome == "workflow_gone":
        run = tasks_api._get_visible_run(run_id, task_id, team_id)
        if run is None:
            return "not_found", None
        if run.is_terminal:
            return "already_terminal", tasks_api._task_run_detail_to_dto(run)
        stream_generation = (run.state or {}).get("stream_generation")
        if not isinstance(stream_generation, str) or not stream_generation:
            try:
                stream_generation = get_task_run_stream_generation(str(run.id), run_uses_dedicated_stream(run.state))
            except Exception:
                logger.warning("Failed to read stream generation for cancelled run %s", run.id, exc_info=True)
                stream_generation = TASK_RUN_STREAM_INITIAL_GENERATION
        if not _cleanup_run_without_workflow(run):
            return "unavailable", tasks_api._task_run_detail_to_dto(run)
        TaskRun.update_state_atomic(
            run.id,
            updates={"cancel_fallback_cleanup_complete": True, "cancel_fallback_stream_generation": stream_generation},
        )
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

    capture_cancel_request(run, signal_outcome)
    return "accepted", dto
