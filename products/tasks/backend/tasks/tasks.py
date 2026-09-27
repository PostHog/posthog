from datetime import datetime
from uuid import UUID

from celery import shared_task

from products.tasks.backend.facade.api import record_comment_activity
from products.tasks.backend.logic.services.comment_slack_dm import send_comment_slack_dms
from products.tasks.backend.logic.services.slack_pr_cards import post_pr_closed_slack_update
from products.tasks.backend.logic.services.workflow_step_resume import resume_workflow_step_for_run_id
from products.tasks.backend.logic.stream.budget_steer import BudgetSteerCapture, BudgetSteerProperties


@shared_task(ignore_result=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5, acks_late=True)
def capture_budget_steer(*, team_id: int, event_uuid: str, timestamp: str, properties: BudgetSteerProperties) -> None:
    BudgetSteerCapture.capture(team_id, event_uuid, timestamp, properties)


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


# No retries: the wake is best-effort by design, and the parked step has its own deadline.
@shared_task(ignore_result=True)
def resume_workflow_step_for_run_deferred(run_id: str) -> None:
    resume_workflow_step_for_run_id(run_id)


# No retries: the task records the close before the post, so a retry finds it and posts nothing.
@shared_task(ignore_result=True)
def notify_slack_thread_pr_closed(run_id: str, pr_url: str, merged: bool = False) -> None:
    post_pr_closed_slack_update(run_id, pr_url, merged=merged)


# No retries: the run records the event before it goes out, so a retry finds it and sends nothing.
@shared_task(ignore_result=True)
def dispatch_loop_pr_notification_task(run_id: str, event: str, pr_url: str) -> None:
    from products.tasks.backend.logic.services.loop_runs import (  # noqa: PLC0415 (keep temporalio off the celery import path)
        dispatch_loop_pr_notification,
    )

    dispatch_loop_pr_notification(run_id, event, pr_url)
