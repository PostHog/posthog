from datetime import timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.utils import timezone

from posthog.models.group.util import raw_create_group_ch
from posthog.models.utils import uuid7
from posthog.test.persons import create_group_type_mapping

from products.error_tracking.backend.logic.recommendations.many_accounts import ManyAccountsRecommendation
from products.error_tracking.backend.logic.recommendations.one_account import OneAccountRecommendation
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    sync_issues_to_clickhouse,
)


class TestAccountLenses(ClickhouseTestMixin, BaseTest):
    def _create_issue(self, name: str) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(
            id=uuid7(), team=self.team, status=ErrorTrackingIssue.Status.ACTIVE, name=name, description="boom"
        )
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=f"fp::{issue.id}")
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=self.team.pk)
        return issue

    def _visit(self, account: str, issue: ErrorTrackingIssue | None = None) -> None:
        session_id = str(uuid7())
        recent = (timezone.now() - timedelta(hours=2)).isoformat()
        properties = {"$session_id": session_id, "$group_0": account}
        _create_event(
            distinct_id=session_id, event="$pageview", team=self.team, properties=properties, timestamp=recent
        )
        if issue:
            _create_event(
                distinct_id=session_id,
                event="$exception",
                team=self.team,
                properties={**properties, "$exception_fingerprint": f"fp::{issue.id}"},
                timestamp=recent,
            )

    def test_flags_issues_that_reach_many_accounts_or_one_account(self):
        create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
            name_plural="organizations",
        )
        raw_create_group_ch(self.team.pk, 0, "org-big", {"name": "Big Customer"}, timezone.now())
        shared = self._create_issue("SharedQuota")
        one_customer = self._create_issue("OneCustomer")
        # 100 active organizations, 20 of which hit the shared issue.
        for i in range(100):
            self._visit(f"org-{i:03d}", shared if i < 20 else None)
        # One organization causes 24 of the 25 sessions of the other issue.
        for i in range(25):
            self._visit("org-big" if i < 24 else "org-001", one_customer)
        flush_persons_and_events()

        many = ManyAccountsRecommendation().compute(self.team)
        one = OneAccountRecommendation().compute(self.team)

        self.assertTrue(many["evaluable"])
        self.assertEqual(many["group_label"], "organizations")
        # 101 active organizations: the 100 above plus the big customer.
        self.assertEqual(
            [(i["name"], i["accounts"], i["account_share"]) for i in many["issues"]], [("SharedQuota", 20, 0.198)]
        )
        self.assertEqual(
            [(i["name"], i["top_account"]) for i in one["issues"]],
            [("OneCustomer", {"key": "org-big", "name": "Big Customer", "session_share": 0.96})],
        )
