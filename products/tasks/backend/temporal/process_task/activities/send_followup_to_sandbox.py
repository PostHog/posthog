import json
from dataclasses import dataclass

import structlog
from django_redis import get_redis_connection
from temporalio import activity

from products.tasks.backend.models import TaskRun
from products.tasks.backend.services.agent_command import send_user_message
from products.tasks.backend.services.connection_token import create_sandbox_connection_token
from products.tasks.backend.services.sandbox import SANDBOX_TTL_SECONDS
from products.tasks.backend.stream.redis_stream import get_task_run_stream_key

from ee.hogai.sandbox import TURN_COMPLETE_METHOD

logger = structlog.get_logger(__name__)


@dataclass
class SendFollowupToSandboxInput:
    run_id: str
    message: str


@activity.defn
def send_followup_to_sandbox(input: SendFollowupToSandboxInput) -> None:
    """Send a follow-up user message to the sandbox and write result markers to Redis.

    Called by the workflow when it receives a send_followup_message signal from the
    web layer. Writes turn_complete on success or an error event on failure so the
    SSE stream terminates cleanly.
    """
    try:
        task_run = TaskRun.objects.select_related("task__created_by").get(id=input.run_id)
    except TaskRun.DoesNotExist:
        error_msg = "Task run not found"
        logger.warning("send_followup_run_not_found", run_id=input.run_id)
        _write_error_and_complete(input.run_id, error_msg)
        # Raise so the workflow can mark the run as failed. Without this,
        # background-mode runs hang until the inactivity timeout because
        raise RuntimeError(f"send_followup failed: {error_msg}")

    auth_token = None
    created_by = task_run.task.created_by
    if created_by and created_by.id:
        distinct_id = created_by.distinct_id or f"user_{created_by.id}"
        auth_token = create_sandbox_connection_token(task_run, user_id=created_by.id, distinct_id=distinct_id)

    result = send_user_message(task_run, input.message, auth_token=auth_token, timeout=SANDBOX_TTL_SECONDS)

    if result.success:
        _write_turn_complete(input.run_id)
        logger.info("send_followup_delivered", run_id=input.run_id)
    else:
        logger.warning(
            "send_followup_failed",
            run_id=input.run_id,
            error=result.error,
            status_code=result.status_code,
        )
        error_msg = result.error or "Failed to send message to sandbox"
        _write_error_and_complete(input.run_id, error_msg)
        # Propagate failure to the workflow.
        raise RuntimeError(f"send_followup failed: {error_msg}")


def _write_turn_complete(run_id: str) -> None:
    """Write a synthetic turn_complete event to the Redis stream."""
    stream_key = get_task_run_stream_key(run_id)
    event = {
        "type": "notification",
        "notification": {
            "method": TURN_COMPLETE_METHOD,
            "params": {"source": "posthog"},
        },
    }
    conn = get_redis_connection("default")
    conn.xadd(stream_key, {"data": json.dumps(event)}, maxlen=2000)


def _write_error_and_complete(run_id: str, error_message: str) -> None:
    """Write an error event followed by turn_complete to the Redis stream."""
    stream_key = get_task_run_stream_key(run_id)
    conn = get_redis_connection("default")

    error_event = {
        "type": "notification",
        "notification": {
            "method": "_posthog/error",
            "params": {"message": error_message},
        },
    }
    conn.xadd(stream_key, {"data": json.dumps(error_event)}, maxlen=2000)
    _write_turn_complete(run_id)
