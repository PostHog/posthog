from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.schema import HogQLQueryResponse

from products.signals.backend.models import SignalReport
from products.signals.backend.report_chart_refresh import refresh_report_chart_snapshots


class TestReportChartRefresh(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(
            team=self.team,
            charts=[
                {
                    "chart_id": "events",
                    "title": "Events",
                    "query": {
                        "kind": "DataVisualizationNode",
                        "source": {"kind": "HogQLQuery", "query": "SELECT count() FROM events"},
                    },
                }
            ],
        )

    def test_saves_results_and_reopening_reuses_a_fresh_snapshot(self) -> None:
        with patch(
            "posthog.hogql_queries.hogql_query_runner.HogQLQueryRunner.run",
            return_value=HogQLQueryResponse(results=[[7]], columns=["count"], types=["Int64"]),
        ) as query:
            refresh_report_chart_snapshots(self.team.id, str(self.report.id))
            self.report.refresh_from_db()
            assert self.report.charts[0]["cached_results"]["results"] == [[7]]
            refresh_report_chart_snapshots(self.team.id, str(self.report.id))
            assert query.call_count == 1

    @parameterized.expand([("failure", False), ("concurrent_edit", True)])
    def test_refresh_preserves_previous_evidence(self, _name: str, concurrent_edit: bool) -> None:
        previous = {"results": [[3]]}
        self.report.charts[0].update(
            cached_results=previous, cached_results_at=(timezone.now() - timedelta(hours=1)).isoformat()
        )
        self.report.save(update_fields=["charts"])

        def run(*args: object, **kwargs: object) -> HogQLQueryResponse:
            if concurrent_edit:
                SignalReport.objects.filter(id=self.report.id).update(charts=[])
                return HogQLQueryResponse(results=[[7]], columns=["count"], types=["Int64"])
            raise TimeoutError("Query timed out")

        with patch("posthog.hogql_queries.hogql_query_runner.HogQLQueryRunner.run", side_effect=run):
            refresh_report_chart_snapshots(self.team.id, str(self.report.id))
        self.report.refresh_from_db()
        assert self.report.charts == [] if concurrent_edit else self.report.charts[0]["cached_results"] == previous
