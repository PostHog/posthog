from datetime import datetime
from uuid import UUID

from celery import shared_task

from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.facade.api import record_comment_activity
from products.tasks.backend.logic.services.comment_slack_dm import send_comment_slack_dms


@shared_task(ignore_result=True)
def dispatch_task_processing_workflow(
    *,
    task_id: str,
    run_id: str,
    team_id: int,
    user_id: int | None,
    create_pr: bool,
    slack_thread_context: dict | None,
    posthog_mcp_scopes: PosthogMcpScopes,
    prewarmed: bool,
    workflow_id_prefix: str | None,
    initial_message: dict | None,
) -> None:
    from products.tasks.backend.temporal.client import execute_task_processing_workflow
    from products.tasks.backend.temporal.process_task.workflow import PendingFollowup

    execute_task_processing_workflow(
        task_id=task_id,
        run_id=run_id,
        team_id=team_id,
        user_id=user_id,
        create_pr=create_pr,
        slack_thread_context=slack_thread_context,
        posthog_mcp_scopes=posthog_mcp_scopes,
        prewarmed=prewarmed,
        workflow_id_prefix=workflow_id_prefix,
        initial_message=PendingFollowup(**initial_message) if initial_message else None,
    )


@shared_task(ignore_result=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def project_task_comment_activity(
    *,
    team_id: int,
    comment_id: str,
    mentioned_user_ids: list[int],
    include_relationship_recipients: bool,
    target_owner_id: int | None,
    activity_at: str | None,
) -> None:
    record_comment_activity(
        team_id=team_id,
        comment_id=UUID(comment_id),
        mentioned_user_ids=mentioned_user_ids,
        include_relationship_recipients=include_relationship_recipients,
        target_owner_id=target_owner_id,
        activity_at=datetime.fromisoformat(activity_at) if activity_at else None,
    )


# No retries: the Activity row already carries the notification, so a dropped DM is recoverable
# while a re-sent one is not.
@shared_task(ignore_result=True)
def deliver_comment_slack_dms(
    *,
    team_id: int,
    comment_id: str,
    task_id: str,
    recipients: dict[str, str],
) -> None:
    send_comment_slack_dms(
        team_id=team_id,
        comment_id=UUID(comment_id),
        task_id=UUID(task_id),
        recipients={int(user_id): kind for user_id, kind in recipients.items()},
    )
