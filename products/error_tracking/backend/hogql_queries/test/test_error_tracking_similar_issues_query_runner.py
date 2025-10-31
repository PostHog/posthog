from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries

from posthog.schema import ErrorTrackingSimilarIssuesQuery

from products.error_tracking.backend.hogql_queries.error_tracking_similar_issues_query_runner import (
    ErrorTrackingSimilarIssuesQueryRunner,
)


class TestErrorTrackingSimilarIssuesQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _calculate(
        self,
    ):
        return (
            ErrorTrackingSimilarIssuesQueryRunner(
                team=self.team,
                query=ErrorTrackingSimilarIssuesQuery(
                    kind="ErrorTrackingSimilarIssuesQuery",
                    issueId="019a2f10-49b0-7be3-8758-f5c03542e2db",
                    maxDistance=1000,
                ),
            )
            .calculate()
            .model_dump()
        )

    @snapshot_clickhouse_queries
    def test_column_names(self):
        results = self._calculate()["results"]
        self.assertEqual(
            results,
            [],
        )
