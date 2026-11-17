import uuid
from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from products.error_tracking.backend.models import ErrorTrackingIssueChange
from products.error_tracking.backend.temporal.issue_change_cleanup.activities import cleanup_issue_changes_activity
from products.error_tracking.backend.temporal.issue_change_cleanup.types import (
    IssueChangeCleanupInputs,
    IssueChangeCleanupResult,
)


class TestIssueChangeCleanupActivity(BaseTest):
    def _change(self, *, days_ago: int, dispatched: bool) -> ErrorTrackingIssueChange:
        created_at = timezone.now() - timedelta(days=days_ago)
        change = ErrorTrackingIssueChange.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            issue_id=uuid.uuid4(),
            kind="created",
            operation_id=uuid.uuid4(),
            actor_type="ingestion",
            dispatched_at=created_at if dispatched else None,
        )
        # `created_at` is set on insert, so the row's age is written after.
        ErrorTrackingIssueChange.objects.for_team(self.team.id).filter(id=change.id).update(created_at=created_at)
        return change

    def test_deletes_every_change_past_the_retention_in_batches(self) -> None:
        self._change(days_ago=8, dispatched=True)
        # Still undispatched after a week, so no longer news.
        self._change(days_ago=8, dispatched=False)
        recent = self._change(days_ago=6, dispatched=False)

        with patch("products.error_tracking.backend.temporal.issue_change_cleanup.activities.close_old_connections"):
            result = cleanup_issue_changes_activity(IssueChangeCleanupInputs(batch_size=1))

        assert result == IssueChangeCleanupResult(deleted_count=2)
        assert list(ErrorTrackingIssueChange.objects.for_team(self.team.id).values_list("id", flat=True)) == [recent.id]
