from dataclasses import dataclass

import structlog
from temporalio import activity

from posthog.models.user import User
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.logic.services.agent_command import send_agent_command, send_user_message
from products.tasks.backend.logic.services.connection_token import create_sandbox_connection_token
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.process_task.utils import get_actor_distinct_id

logger = structlog.get_logger(__name__)

PERMISSION_DENIAL_FOLLOWUP_TIMEOUT_SECONDS = 5
PERMISSION_RESPONSE_TIMEOUT_SECONDS = 30


@dataclass
class SendPermissionResponseToSandboxInput:
    run_id: str
    request_id: str
    option_id: str
    actor_user_id: int
    actor_slack_user_id: str | None = None
    is_denial: bool = False
    denial_message: str | None = None
    broker_reason: str | None = None


@activity.defn
@close_db_connections
def send_permission_response_to_sandbox(input: SendPermissionResponseToSandboxInput) -> None:
    """Deliver an agent permission response from the durable task workflow."""
    try:
        task_run = TaskRun.objects.select_related("task", "task__created_by", "task__team").get(id=input.run_id)
    except TaskRun.DoesNotExist as e:
        logger.warning("permission_response_run_not_found", run_id=input.run_id, request_id=input.request_id)
        raise RuntimeError("Task run not found") from e

    try:
        actor = User.objects.get(id=input.actor_user_id)
    except User.DoesNotExist as e:
        logger.warning(
            "permission_response_actor_not_found",
            run_id=input.run_id,
            request_id=input.request_id,
            actor_user_id=input.actor_user_id,
        )
        raise RuntimeError("Permission response actor not found") from e

    auth_token = create_sandbox_connection_token(
        task_run,
        user_id=actor.id,
        distinct_id=get_actor_distinct_id(actor),
    )

    if input.is_denial and input.denial_message:
        denial_result = send_user_message(
            task_run,
            input.denial_message,
            auth_token=auth_token,
            timeout=PERMISSION_DENIAL_FOLLOWUP_TIMEOUT_SECONDS,
        )
        if not denial_result.success:
            logger.warning(
                "permission_response_denial_followup_failed",
                run_id=input.run_id,
                request_id=input.request_id,
                option_id=input.option_id,
                status_code=denial_result.status_code,
                error=denial_result.error,
            )
            raise RuntimeError(denial_result.error or "Failed to send permission denial follow-up")

    result = send_agent_command(
        task_run,
        method="permission_response",
        params={"requestId": input.request_id, "optionId": input.option_id},
        auth_token=auth_token,
        timeout=PERMISSION_RESPONSE_TIMEOUT_SECONDS,
    )
    if not result.success:
        logger.warning(
            "permission_response_delivery_failed",
            run_id=input.run_id,
            request_id=input.request_id,
            option_id=input.option_id,
            status_code=result.status_code,
            error=result.error,
        )
        raise RuntimeError(result.error or "Failed to deliver permission response to sandbox")

    updates: dict[str, object] = {
        "slack_actor_user_id": actor.id,
        "slack_permission_response_last_request_id": input.request_id,
        "slack_permission_response_last_option_id": input.option_id,
    }
    if input.actor_slack_user_id:
        updates["slack_actor_slack_user_id"] = input.actor_slack_user_id
    if input.broker_reason:
        updates["slack_permission_broker_last_reason"] = input.broker_reason
    if input.is_denial:
        updates.update(
            {
                "slack_permission_rejected": True,
                "slack_permission_rejected_request_id": input.request_id,
            }
        )

    TaskRun.update_state_atomic(task_run.id, updates=updates)
    logger.info(
        "permission_response_delivered",
        run_id=input.run_id,
        request_id=input.request_id,
        option_id=input.option_id,
        actor_user_id=actor.id,
        actor_slack_user_id=input.actor_slack_user_id,
        broker_reason=input.broker_reason,
        is_denial=input.is_denial,
    )
