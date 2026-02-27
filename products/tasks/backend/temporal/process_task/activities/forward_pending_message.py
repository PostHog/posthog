from temporalio import activity

from posthog.temporal.common.logger import get_logger

logger = get_logger(__name__)


@activity.defn
def forward_pending_user_message(run_id: str) -> None:
    """Forward a pending user message stored in task run state to the sandbox agent.

    Called after the agent server is ready. Clears the message from state on
    successful delivery or non-retryable failure. Keeps it in state on retryable
    failure to preserve recoverability.
    """
    from products.tasks.backend.models import TaskRun
    from products.tasks.backend.services.agent_command import send_user_message
    from products.tasks.backend.services.connection_token import create_sandbox_connection_token

    try:
        task_run = TaskRun.objects.select_related("task__created_by").get(id=run_id)
    except TaskRun.DoesNotExist:
        logger.warning("forward_pending_message_run_not_found", run_id=run_id)
        return

    state = task_run.state or {}
    pending_message = state.get("pending_user_message")
    if not pending_message:
        return

    auth_token = None
    created_by = task_run.task.created_by
    if created_by and created_by.id:
        distinct_id = created_by.distinct_id or f"user_{created_by.id}"
        auth_token = create_sandbox_connection_token(task_run, user_id=created_by.id, distinct_id=distinct_id)

    result = send_user_message(task_run, pending_message, auth_token=auth_token)
    if not result.success and result.retryable:
        result = send_user_message(task_run, pending_message, auth_token=auth_token, timeout=45)

    if not result.success and result.retryable:
        logger.warning(
            "forward_pending_message_retryable_failure",
            run_id=run_id,
            error=result.error,
        )
        return

    state.pop("pending_user_message", None)
    task_run.state = state
    task_run.save(update_fields=["state", "updated_at"])

    if result.success:
        logger.info("forward_pending_message_delivered", run_id=run_id)
    else:
        logger.warning(
            "forward_pending_message_non_retryable_failure",
            run_id=run_id,
            error=result.error,
        )
