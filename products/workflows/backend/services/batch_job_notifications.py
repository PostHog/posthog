"""Tells the author when a batch run that waited for its realtime cohort ends without a send."""

from uuid import UUID

import structlog

from posthog.email import EmailMessage, get_email_team_and_org_context, is_email_available
from posthog.event_usage import report_user_action
from posthog.helpers.email_utils import sanitize_display_name
from posthog.models import User
from posthog.models.messaging import MessagingRecord
from posthog.models.organization_notification_lock import effective_notification_settings, notification_locks_for_users

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    TargetType,
    create_notification,
)
from products.workflows.backend.facade.enums import HogFlowBatchJobState
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob
from products.workflows.backend.services.proposal_notifications import defanged, user_can_receive

logger = structlog.get_logger(__name__)

EMAIL_SETTING = "workflow_batch_run_not_sent"


def _run_path(job: HogFlowBatchJob) -> str:
    if job.hog_flow.origin_product == "broadcasts":
        return f"/project/{job.team_id}/broadcasts/{job.hog_flow_id}"
    return f"/project/{job.team_id}/workflows/{job.hog_flow_id}/invocations"


def _send_email(user: User, job: HogFlowBatchJob, workflow_name: str, path: str) -> None:
    if not is_email_available(with_absolute_urls=True):
        return
    campaign_key = f"workflow_batch_run_not_sent_{job.id}"
    if MessagingRecord.objects.filter(campaign_key=campaign_key, sent_at__isnull=False).exists():
        return
    locks = notification_locks_for_users([user.id], organization_id=job.team.organization_id).get(user.id, {})
    if not effective_notification_settings(user, locks=locks).get(EMAIL_SETTING, True):
        return
    team_context = get_email_team_and_org_context(team=job.team)
    if "team_name" in team_context:
        team_context["team_name"] = defanged(team_context["team_name"])
    message = EmailMessage(
        campaign_key=campaign_key,
        template_name="workflow_batch_run_not_sent",
        subject=f"{workflow_name} was not sent",
        template_context={
            "workflow_name": workflow_name,
            "timed_out": job.status == HogFlowBatchJobState.FAILED,
            "run_path": path,
            **team_context,
        },
    )
    message.add_user_recipient(user)
    message.send(send_async=True)


def notify_waiting_batch_job_ended(*, team_id: int, batch_job_id: UUID, ended_by_user_id: int | None) -> None:
    """Call after a run moves from waiting to failed or cancelled."""
    job = (
        HogFlowBatchJob.objects.filter(
            id=batch_job_id,
            team_id=team_id,
            status__in=[HogFlowBatchJobState.FAILED, HogFlowBatchJobState.CANCELLED],
        )
        .select_related("hog_flow", "team", "created_by")
        .first()
    )
    if job is None or job.created_by is None:
        return
    author = job.created_by
    try:
        report_user_action(
            author,
            "hog_flow_batch_job_wait_ended",
            {
                "workflow_id": str(job.hog_flow_id),
                "batch_job_id": str(job.id),
                "origin_product": job.hog_flow.origin_product,
                "status": job.status,
                "stopped_by_author": author.id == ended_by_user_id,
            },
            team=job.team,
        )
    except Exception:
        logger.warning("waiting_batch_job_notification.capture_failed", batch_job_id=str(batch_job_id))
    # The author who stops their own run already knows it did not send.
    if author.id == ended_by_user_id or not user_can_receive(author, job.team, job.hog_flow):
        return

    path = _run_path(job)
    workflow_name = defanged(
        sanitize_display_name(
            job.hog_flow.name or "",
            fallback="Your workflow",
            context={"helper": "workflow_batch_run_not_sent_email", "field": "workflow_name"},
        )
    )
    if job.status == HogFlowBatchJobState.FAILED:
        body = (
            "Its cohort did not finish calculating within 24 hours, so nobody got it. "
            "Start it again once the cohort is ready."
        )
    else:
        body = "Someone stopped it while it waited for its cohort to finish calculating, so nobody got it."
    try:
        create_notification(
            NotificationData(
                team_id=team_id,
                notification_type=NotificationType.WORKFLOW_BATCH_RUN_NOT_SENT,
                title=f"{job.hog_flow.name or 'Your workflow'} was not sent"[:100],
                body=body,
                target_type=TargetType.USER,
                target_id=str(author.id),
                resource_type="hog_flow",
                resource_id=str(job.hog_flow_id),
                source_url=path,
                idempotency_key=f"workflow_batch_run_not_sent:{job.id}",
            )
        )
    except Exception:
        logger.exception("waiting_batch_job_notification.in_app_failed", batch_job_id=str(batch_job_id))
    try:
        _send_email(author, job, workflow_name, path)
    except Exception:
        logger.exception("waiting_batch_job_notification.email_failed", batch_job_id=str(batch_job_id))
