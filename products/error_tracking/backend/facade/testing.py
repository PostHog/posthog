"""Test-support facade for error_tracking.

Outside test suites (core's weekly digest, the metrics error overlay) plant issues and
spike events. They get them here instead of importing the models.
"""

from datetime import datetime
from uuid import UUID

from posthog.schema import ErrorTrackingIssueStatus

from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingSpikeEvent


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


def create_spike_event(
    *,
    team_id: int,
    issue_id: UUID,
    detected_at: datetime,
    computed_baseline: float = 1.0,
    current_bucket_value: int = 10,
) -> UUID:
    spike = ErrorTrackingSpikeEvent.objects.create(
        team_id=team_id,
        issue_id=issue_id,
        detected_at=detected_at,
        computed_baseline=computed_baseline,
        current_bucket_value=current_bucket_value,
    )
    return spike.id
