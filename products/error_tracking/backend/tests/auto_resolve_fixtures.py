from datetime import timedelta
from uuid import uuid4

from posthog.test.base import _create_event, flush_persons_and_events

from django.utils import timezone

from posthog.models import Team, User

from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
    sync_issues_to_clickhouse,
)


def create_issue_with_exceptions(
    team: Team,
    *,
    status: str = ErrorTrackingIssue.Status.ACTIVE,
    created_days_ago: int = 30,
    state_updated_days_ago: int | None = None,
    exception_days_ago: list[list[int]] | None = None,
    assignee: User | None = None,
) -> ErrorTrackingIssue:
    """Create an issue with one fingerprint per inner list of `exception_days_ago`, each holding its exception ages."""
    issue = ErrorTrackingIssue.objects.create(team=team, status=status, name="TypeError")
    ErrorTrackingIssue.objects.filter(id=issue.id).update(
        created_at=timezone.now() - timedelta(days=created_days_ago),
        state_updated_at=None
        if state_updated_days_ago is None
        else timezone.now() - timedelta(days=state_updated_days_ago),
    )
    issue.refresh_from_db()
    if assignee is not None:
        ErrorTrackingIssueAssignment.objects.create(team=team, issue=issue, user=assignee)
    fingerprints = [(str(uuid4()), ages) for ages in (exception_days_ago or [[]])]
    for fingerprint, _ in fingerprints:
        ErrorTrackingIssueFingerprintV2.objects.create(team=team, issue=issue, fingerprint=fingerprint)
    sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=team.pk)
    for fingerprint, ages in fingerprints:
        for age in ages:
            _create_event(
                team=team,
                event="$exception",
                distinct_id="user",
                timestamp=timezone.now() - timedelta(days=age),
                properties={"$exception_fingerprint": fingerprint},
            )
    flush_persons_and_events()
    return issue
