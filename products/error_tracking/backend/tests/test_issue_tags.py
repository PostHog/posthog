from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction

from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueTag


class TestIssueTagStorage(BaseTest):
    def test_an_issue_holds_one_answer_per_tag(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        ErrorTrackingIssueTag.objects.for_team(self.team.id).create(
            team=self.team, issue=issue, key="blocks_checkout", value=True, source="jev", question_version=1
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            ErrorTrackingIssueTag.objects.for_team(self.team.id).create(
                team=self.team, issue=issue, key="blocks_checkout", value=False, source="manual", question_version=1
            )
