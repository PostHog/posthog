from typing import Any, Literal

import structlog

from posthog.dataclasses import frozen
from posthog.models import User
from posthog.tasks.email import send_error_tracking_issue_assigned

from products.error_tracking.backend.logic import build_issue_permalink_path, get_canonical_fingerprint
from products.error_tracking.backend.logic.assignees import assignee_property
from products.error_tracking.backend.logic.issue_changes import AssigneeRef
from products.error_tracking.backend.logic.lifecycle_events import (
    ISSUE_ASSIGNED_EVENT,
    produce_issue_lifecycle_event_on_commit,
)
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

    def resolve(self, target_type: TargetType, target_id: str, team_id: int | None) -> list[int]:
        users = super().resolve(target_type, target_id, team_id)
        return [uid for uid in users if uid != self._assigner_id]


@frozen
class AssignmentActor:
    label: str
    user_id: int | None

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError("label is required")

    @property
    def trigger(self) -> Literal["manual", "automatic"]:
        return "manual" if self.user_id is not None else "automatic"

    @classmethod
    def from_user(cls, user: User) -> "AssignmentActor":
        return cls(label=user.first_name or user.email, user_id=user.id)

    @classmethod
    def automatic(cls, label: str) -> "AssignmentActor":
        return cls(label=label, user_id=None)


def dispatch_issue_assigned_realtime(
    *,
    assignment: ErrorTrackingIssueAssignment,
    assignee: dict[str, Any],
    actor: AssignmentActor,
) -> None:
    """Fire one in-app issue_assigned notification for the new assignee.

    - User assignment: skip if the actor is the assignee.
    - Role assignment: target the role; resolver excludes the acting user.
    Never raises — caller's email enqueue must succeed independently.
    """
    try:
        issue = assignment.issue
        # Cymbal writes rule assignments without team_id, so the issue is the only reliable source of the team.
        team = issue.team
        title = f"{actor.label} assigned an issue to you"[:100]
        metadata = {"trigger": actor.trigger}
        body = (issue.name or "")[:200]
        fingerprint = get_canonical_fingerprint(team_id=issue.team_id, issue_id=issue.id)
        source_url = build_issue_permalink_path(project_id=team.project_id, issue_id=issue.id, fingerprint=fingerprint)

        if assignee["type"] == "user":
            if int(assignee["id"]) == actor.user_id:
                return
            target_type = TargetType.USER
            resolver = None
        elif assignee["type"] == "role":
            target_type = TargetType.ROLE
            resolver = _AssignerExcludingResolver(assigner_id=actor.user_id) if actor.user_id is not None else None
        else:
            return
        create_notification(
            NotificationData(
                team_id=issue.team_id,
                notification_type=NotificationType.ISSUE_ASSIGNED,
                priority=Priority.NORMAL,
                title=title,
                body=body,
                target_type=target_type,
                target_id=str(assignee["id"]),
                resource_type="error_tracking",
                resource_id=str(issue.id),
                source_url=source_url,
                source_type=SourceType.ERROR_TRACKING,
                source_id=str(issue.id),
                metadata=metadata,
                resolver=resolver,
            )
        )
    except Exception as e:
        logger.exception(
            "issue_assigned.realtime_failed",
            issue_id=str(assignment.issue_id),
            error=str(e),
        )


def notify_automatic_assignment(
    *,
    assignment: ErrorTrackingIssueAssignment,
    assignee: AssigneeRef,
    label: str,
) -> None:
    """Tell the assignee about an assignment that no person made, and emit `$error_tracking_issue_assigned`.

    Raises when the lifecycle event cannot be built or the email cannot be queued, so the caller can count the failure.
    The in-app notification goes first, so the assignee still gets it when the event or the email raises.
    """
    actor = AssignmentActor.automatic(label)
    dispatch_issue_assigned_realtime(assignment=assignment, assignee=assignee.to_json(), actor=actor)
    produce_issue_lifecycle_event_on_commit(
        event=ISSUE_ASSIGNED_EVENT,
        issue=assignment.issue,
        user=None,
        extra_properties={"assignee": assignee_property(assignee.to_json())},
    )
    send_error_tracking_issue_assigned.delay(assignment.id, None, actor.label)
