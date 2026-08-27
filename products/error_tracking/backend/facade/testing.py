"""Test-support facade for error_tracking.

Core's weekly-digest tests plant issues with a chosen creation time. They get them here
instead of importing the model.
"""

from datetime import datetime
from uuid import UUID

from posthog.schema import ErrorTrackingIssueStatus

from products.error_tracking.backend.models import ErrorTrackingIssue


def create_issue(
    *,
    team_id: int,
    name: str,
    status: ErrorTrackingIssueStatus = ErrorTrackingIssueStatus.ACTIVE,
    created_at: datetime | None = None,
) -> UUID:
    issue = ErrorTrackingIssue.objects.create(team_id=team_id, name=name, status=status)
    if created_at is not None:
        # created_at is auto_now_add, so it can only be set after the insert.
        ErrorTrackingIssue.objects.filter(id=issue.id).update(created_at=created_at)
    return issue.id
