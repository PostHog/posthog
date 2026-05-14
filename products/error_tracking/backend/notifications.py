from typing import Any

import structlog

from posthog.models import User

from products.error_tracking.backend.models import ErrorTrackingIssueAssignment
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    RecipientsResolver,
    SourceType,
    TargetType,
    create_notification,
)

logger = structlog.get_logger(__name__)


class _AssignerExcludingResolver(RecipientsResolver):
    def __init__(self, assigner_id: int) -> None:
        super().__init__()
        self._assigner_id = assigner_id

    def resolve(self, target_type: TargetType, target_id: str, team_id: int) -> list[int]:
        users = super().resolve(target_type, target_id, team_id)
        return [uid for uid in users if uid != self._assigner_id]


def dispatch_issue_assigned_realtime(
    *,
    assignment: ErrorTrackingIssueAssignment,
    assignee: dict[str, Any],
    assigner: User,
) -> None:
    """Fire one in-app issue_assigned notification for the new assignee.

    - User assignment: skip if assigner == assignee.
    - Role assignment: target the role; resolver excludes the assigner.
    Never raises — caller's email enqueue must succeed independently.
    """
    try:
        if assignment.team_id is None:
            return
        team = assignment.team
        assert team is not None  # team_id is set, so the FK is non-null (Django stubs disagree)
        issue = assignment.issue
        title = f"{assigner.first_name or assigner.email} assigned an issue to you"[:100]
        body = (issue.name or "")[:200]
        source_url = f"/project/{team.project_id}/error_tracking/{issue.id}"

        if assignee["type"] == "user":
            if int(assignee["id"]) == assigner.id:
                return
            create_notification(
                NotificationData(
                    team_id=assignment.team_id,
                    notification_type=NotificationType.ISSUE_ASSIGNED,
                    priority=Priority.NORMAL,
                    title=title,
                    body=body,
                    target_type=TargetType.USER,
                    target_id=str(assignee["id"]),
                    resource_type="error_tracking",
                    resource_id=str(issue.id),
                    source_url=source_url,
                    source_type=SourceType.ERROR_TRACKING,
                    source_id=str(issue.id),
                )
            )
        elif assignee["type"] == "role":
            create_notification(
                NotificationData(
                    team_id=assignment.team_id,
                    notification_type=NotificationType.ISSUE_ASSIGNED,
                    priority=Priority.NORMAL,
                    title=title,
                    body=body,
                    target_type=TargetType.ROLE,
                    target_id=str(assignee["id"]),
                    resource_type="error_tracking",
                    resource_id=str(issue.id),
                    source_url=source_url,
                    source_type=SourceType.ERROR_TRACKING,
                    source_id=str(issue.id),
                    resolver=_AssignerExcludingResolver(assigner_id=assigner.id),
                )
            )
    except Exception as e:
        logger.exception(
            "issue_assigned.realtime_failed",
            issue_id=str(assignment.issue_id),
            error=str(e),
        )
