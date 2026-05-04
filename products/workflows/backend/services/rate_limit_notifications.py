from __future__ import annotations

import structlog

from posthog.models.hog_flow.hog_flow import HogFlow

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)
from products.notifications.backend.facade.enums import NotificationOnlyResourceType, SourceType

logger = structlog.get_logger(__name__)


def handle_workflow_rate_limited(
    team_id: int,
    hog_flow_id: str,
    hog_flow_name: str,
    created_by_id: int | None,
) -> None:
    """Handle a workflow rate-limit notification trigger from the CDP consumer."""

    # Resolve the workflow owner
    if created_by_id is None:
        try:
            hog_flow = HogFlow.objects.only("created_by_id").get(id=hog_flow_id, team_id=team_id)
            created_by_id = hog_flow.created_by_id
        except HogFlow.DoesNotExist:
            logger.warning(
                "workflow_rate_limited_notification_skipped",
                reason="hog_flow_not_found",
                hog_flow_id=hog_flow_id,
                team_id=team_id,
            )
            return

    if created_by_id is None:
        logger.warning(
            "workflow_rate_limited_notification_skipped",
            reason="no_created_by",
            hog_flow_id=hog_flow_id,
            team_id=team_id,
        )
        return

    create_notification(
        NotificationData(
            team_id=team_id,
            notification_type=NotificationType.WORKFLOW_RATE_LIMITED,
            priority=Priority.CRITICAL,
            title=f"Workflow '{hog_flow_name}' is being rate limited",
            body="Events matching this workflow are being dropped because the rate limit was exceeded.",
            target_type=TargetType.USER,
            target_id=str(created_by_id),
            resource_type=NotificationOnlyResourceType.WORKFLOW,
            resource_id=str(hog_flow_id),
            source_url=f"/workflows/{hog_flow_id}/workflow",
            source_type=SourceType.WORKFLOW,
            source_id=str(hog_flow_id),
        )
    )

    logger.info(
        "workflow_rate_limited_notification_sent",
        team_id=team_id,
        hog_flow_id=hog_flow_id,
        created_by_id=created_by_id,
    )
