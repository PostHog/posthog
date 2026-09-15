from datetime import UTC, datetime

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries

from posthog.schema import ErrorTrackingIssueCorrelationQuery

from products.error_tracking.backend.hogql_queries.error_tracking_issue_correlation_query_runner import (
    ErrorTrackingIssueCorrelationQueryRunner,
)
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueFingerprintV2


class TestErrorTrackingIssueCorrelationQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _runner(self) -> ErrorTrackingIssueCorrelationQueryRunner:
        return ErrorTrackingIssueCorrelationQueryRunner(
            team=self.team,
            query=ErrorTrackingIssueCorrelationQuery(
                kind="ErrorTrackingIssueCorrelationQuery",
                events=["$pageview"],
            ),
        )

    def _calculate(
        self,
    ):
        return self._runner().calculate().model_dump()

    @time_machine.travel("2022-01-10T12:11:00", tick=False)
    @snapshot_clickhouse_queries
    def test_column_names(self):
        columns = self._calculate()["columns"]
        self.assertEqual(
            columns,
            [
                "id",
                "status",
                "name",
                "description",
                "first_seen",
                "assignee",
                "external_issues",
                "last_seen",
                "library",
                "odds_ratio",
                "population",
                "event",
            ],
        )

    def test_fetch_issues_reports_earliest_fingerprint_first_seen(self):
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint="later")
        earliest = ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint="earlier")
        ErrorTrackingIssueFingerprintV2.objects.filter(id=earliest.id).update(
            first_seen=datetime(2025, 1, 1, tzinfo=UTC)
        )

        issues = self._runner().fetch_issues([str(issue.id)])

        assert [(row["id"], row["first_seen"]) for row in issues] == [(str(issue.id), "2025-01-01T00:00:00Z")]
