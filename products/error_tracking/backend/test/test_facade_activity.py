from datetime import datetime, timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.utils import timezone

from products.error_tracking.backend.facade import api
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
    sync_issues_to_clickhouse,
)

from ee.clickhouse.materialized_columns.columns import materialize


class TestIssueActivity(ClickhouseTestMixin, APIBaseTest):
    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        materialize("events", "$exception_issue_id", is_nullable=True)

    def _ago(self, days: int) -> datetime:
        return timezone.now() - timedelta(days=days)

    def _issue(
        self, name: str, *, first_seen_days: int = 1, status: str = ErrorTrackingIssue.Status.ACTIVE
    ) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=self.team, name=name, description="boom", status=status)
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=str(uuid4()))
        ErrorTrackingIssueFingerprintV2.objects.filter(issue=issue).update(first_seen=self._ago(first_seen_days))
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=self.team.pk)
        return issue

    def _exception(self, issue: ErrorTrackingIssue, distinct_id: str, days: int, lib: str = "web") -> None:
        fingerprint = (
            ErrorTrackingIssueFingerprintV2.objects.filter(issue=issue)
            .order_by("created_at")
            .values_list("fingerprint", flat=True)[0]
        )
        _create_event(
            team=self.team,
            event="$exception",
            distinct_id=distinct_id,
            properties={"$exception_issue_id": str(issue.id), "$exception_fingerprint": fingerprint, "$lib": lib},
            timestamp=self._ago(days),
        )

    def test_new_issue_activity_counts_only_new_active_unassigned_issues_by_their_oldest_fingerprint(self) -> None:
        for distinct_id in ("user-1", "user-2"):
            _create_person(team=self.team, distinct_ids=[distinct_id])
        new = self._issue("TypeError")
        assigned = self._issue("Assigned")
        ErrorTrackingIssueAssignment.objects.create(issue=assigned, team=self.team, user=self.user)
        resolved = self._issue("Resolved", status=ErrorTrackingIssue.Status.RESOLVED)
        old = self._issue("Old", first_seen_days=30)
        merged = self._issue("Merged")
        older = ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=merged, fingerprint=str(uuid4()))
        ErrorTrackingIssueFingerprintV2.objects.filter(id=older.id).update(first_seen=self._ago(30))
        self._exception(new, "user-1", 1)
        self._exception(new, "user-1", 2, lib="posthog-kmp")
        self._exception(new, "user-2", 2, lib="posthog-python")
        for issue in (assigned, resolved, old, merged):
            self._exception(issue, "user-1", 1)
        flush_persons_and_events()

        found = api.list_new_unassigned_issue_activity(self.team, self.user, limit=5)

        self.assertEqual(
            [(i.name, i.users, i.occurrences, round(i.client_share, 2)) for i in found], [("TypeError", 2, 3, 0.67)]
        )

    def test_quiet_assigned_issues_leave_out_issues_with_recent_events_and_other_assignees(self) -> None:
        quiet = self._issue("Quiet")
        loud = self._issue("Loud")
        theirs = self._issue("Theirs")
        for issue, user in ((quiet, self.user), (loud, self.user), (theirs, self._create_user("other@example.com"))):
            ErrorTrackingIssueAssignment.objects.create(issue=issue, team=self.team, user=user)
        self._exception(quiet, "user-1", 20)
        self._exception(loud, "user-1", 3)
        flush_persons_and_events()

        found = api.list_quiet_issues_assigned_to(self.team, self.user, quiet_days=14, limit=10)

        self.assertEqual([i.id for i in found], [quiet.id])
