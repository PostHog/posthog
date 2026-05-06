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


PRIORITY_MAP: dict[str, Priority] = {
    "normal": Priority.NORMAL,
    "critical": Priority.CRITICAL,
}


def _resolve_target(
    target: str,
    team_id: int,
    created_by_id: int | None,
    hog_flow_id: str,
) -> tuple[TargetType, str] | None:
    """Resolve notification target to (TargetType, target_id), or None to skip."""
    if target == "team":
        return TargetType.TEAM, str(team_id)

    # Default: owner
    if created_by_id is None:
        try:
            hog_flow = HogFlow.objects.only("created_by_id").get(id=hog_flow_id, team_id=team_id)
            created_by_id = hog_flow.created_by_id
        except HogFlow.DoesNotExist:
            logger.warning(
                "workflow_notification_skipped",
                reason="hog_flow_not_found",
                hog_flow_id=hog_flow_id,
                team_id=team_id,
            )
            return None

    if created_by_id is None:
        logger.warning(
            "workflow_notification_skipped",
            reason="no_created_by",
            hog_flow_id=hog_flow_id,
            team_id=team_id,
        )
        return None

    return TargetType.USER, str(created_by_id)


def handle_workflow_rate_limited(
    team_id: int,
    hog_flow_id: str,
    hog_flow_name: str,
    created_by_id: int | None,
    priority: str = "normal",
    target: str = "owner",
) -> None:
    resolved = _resolve_target(target, team_id, created_by_id, hog_flow_id)
    if resolved is None:
        return

    target_type, target_id = resolved

    create_notification(
        NotificationData(
            team_id=team_id,
            notification_type=NotificationType.WORKFLOW_RATE_LIMITED,
            priority=PRIORITY_MAP.get(priority, Priority.NORMAL),
            title=f"Workflow '{hog_flow_name}' is being rate limited",
            body="Events matching this workflow are being dropped because the rate limit was exceeded.",
            target_type=target_type,
            target_id=target_id,
            resource_type=NotificationOnlyResourceType.WORKFLOW,
            resource_id=str(hog_flow_id),
            source_url=f"/workflows/{hog_flow_id}/logs",
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
