from datetime import timedelta
from typing import Any

from django.utils import timezone

import structlog

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)
from products.notifications.backend.facade.enums import NotificationOnlyResourceType
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob

logger = structlog.get_logger(__name__)

NOTIFICATION_THROTTLE = timedelta(hours=24)


def record_skipped_batch_run(
    *,
    hog_flow: HogFlow,
    team_id: int,
    filters: dict,
    variables: dict,
    affected: int,
    limit: int,
    created_by_id: int | None = None,
) -> HogFlowBatchJob:
    skip_reason: dict[str, Any] = {
        "reason": "audience_over_limit",
        "affected": affected,
        "limit": limit,
    }
    job = HogFlowBatchJob.objects.create(
        team_id=team_id,
        hog_flow=hog_flow,
        variables=variables,
        filters=filters,
        status=HogFlowBatchJob.State.SKIPPED,
        skip_reason=skip_reason,
        created_by_id=created_by_id,
    )
    _maybe_notify_owner(hog_flow=hog_flow, team_id=team_id, job=job, affected=affected, limit=limit)
    return job


def _maybe_notify_owner(*, hog_flow: HogFlow, team_id: int, job: HogFlowBatchJob, affected: int, limit: int) -> None:
    owner_id = hog_flow.created_by_id
    if owner_id is None:
        return

    # Throttle: skip the notification if there is already another SKIPPED row for this workflow
    # in the past 24h. The row created in record_skipped_batch_run is excluded so the first
    # skip in a window still fires.
    recent_skip_exists = (
        HogFlowBatchJob.objects.filter(
            hog_flow=hog_flow,
            status=HogFlowBatchJob.State.SKIPPED,
            created_at__gte=timezone.now() - NOTIFICATION_THROTTLE,
        )
        .exclude(id=job.id)
        .exists()
    )
    if recent_skip_exists:
        return

    try:
        create_notification(
            NotificationData(
                team_id=team_id,
                notification_type=NotificationType.PIPELINE_FAILURE,
                priority=Priority.NORMAL,
                title=f"Workflow “{hog_flow.name}” skipped: audience over limit",
                body=(
                    f"The most recent batch run was skipped — audience size {affected:,} "
                    f"exceeded the per-team limit of {limit:,}. Tighten the trigger filters or "
                    "ask to raise the limit."
                ),
                target_type=TargetType.USER,
                target_id=str(owner_id),
                resource_type=NotificationOnlyResourceType.PIPELINE,
                resource_id=str(hog_flow.id),
                source_url=f"/workflows/{hog_flow.id}/logs",
            )
        )
    except Exception:
        logger.exception(
            "Failed to send over-limit skip notification",
            hog_flow_id=str(hog_flow.id),
            team_id=team_id,
        )
