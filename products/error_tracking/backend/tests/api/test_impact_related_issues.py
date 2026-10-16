from datetime import timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.utils import timezone

from posthog.models.utils import uuid7

from products.error_tracking.backend.logic.recommendations.related_issues import RelatedIssuesRecommendation
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    sync_issues_to_clickhouse,
)


class TestRelatedIssuesLens(ClickhouseTestMixin, BaseTest):
    def _create_issue(self, name: str) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(
            id=uuid7(), team=self.team, status=ErrorTrackingIssue.Status.ACTIVE, name=name
        )
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=f"fp::{issue.id}")
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=self.team.pk)
        return issue

    def _create_exception(self, issue: ErrorTrackingIssue, session_id: str, timestamp: str) -> None:
        _create_event(
            distinct_id=session_id,
            event="$exception",
            team=self.team,
            properties={"$session_id": session_id, "$exception_fingerprint": f"fp::{issue.id}"},
            timestamp=timestamp,
        )

    def test_relates_an_issue_to_the_issue_it_causes(self) -> None:
        api_failure = self._create_issue("ApiFailure")
        cart_toast = self._create_issue("CartToast")
        start = timezone.now() - timedelta(hours=3)
        # The API failure is followed by the toast a second later. The toast also appears on its own.
        for i in range(20):
            session_id = str(uuid7())
            at = start + timedelta(minutes=i)
            self._create_exception(api_failure, session_id, at.isoformat())
            self._create_exception(cart_toast, session_id, (at + timedelta(seconds=1)).isoformat())
        for i in range(10):
            self._create_exception(cart_toast, str(uuid7()), (start + timedelta(minutes=30 + i)).isoformat())
        flush_persons_and_events()

        meta = RelatedIssuesRecommendation().compute(self.team)

        self.assertEqual(
            [
                (
                    pair["name"],
                    pair["related"]["name"],
                    pair["relation"],
                    pair["sessions"],
                    pair["related_sessions"],
                    pair["shared_sessions"],
                    pair["leads_share"],
                )
                for pair in meta["issues"]
            ],
            [("ApiFailure", "CartToast", "causes", 20, 30, 20, 1.0)],
        )
