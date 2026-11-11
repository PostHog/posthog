from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.product_analytics.backend.facade.contracts import TrendsQueryRunResult
from products.signals.backend.report_chart_probe import empty_trends_chart_ids
from products.signals.backend.report_charts import ReportChart

RUN_PATH = "products.signals.backend.report_chart_probe.run_cached_trends_query"

TRENDS_QUERY = {
    "kind": "InsightVizNode",
    "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
}


def _chart(query: dict) -> ReportChart:
    return ReportChart(chart_id="pageviews", title="Pageviews", query=query)


class TestEmptyTrendsChartIds(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_series", [], True),
            ("only_zero_buckets", [{"data": [0, 0, 0], "count": 0}], True),
            ("one_non_zero_bucket", [{"data": [0, 3, 0], "count": 3}], False),
            ("zero_series_beside_a_non_zero_one", [{"data": [0, 0]}, {"data": [0, 1]}], False),
            ("aggregated_value_only", [{"data": [], "aggregated_value": 12}], False),
        ]
    )
    def test_classifies_trends_results(self, _name: str, results: list[dict], expected_empty: bool) -> None:
        with patch(RUN_PATH, return_value=TrendsQueryRunResult(results=results)):
            empty = empty_trends_chart_ids(MagicMock(id=1), [_chart(TRENDS_QUERY)])

        assert empty == (["pageviews"] if expected_empty else [])

    def test_a_failed_query_does_not_refuse_the_chart(self) -> None:
        with patch(RUN_PATH, side_effect=TimeoutError("ClickHouse timed out")):
            assert empty_trends_chart_ids(MagicMock(id=1), [_chart(TRENDS_QUERY)]) == []

    @parameterized.expand(
        [
            ("sql_chart", {"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "SELECT 1"}}),
            ("funnel_chart", {"kind": "InsightVizNode", "source": {"kind": "FunnelsQuery", "series": []}}),
            ("saved_insight", {"kind": "SavedInsightNode", "shortId": "abc123"}),
            (
                "box_plot",
                {
                    "kind": "InsightVizNode",
                    "source": {**TRENDS_QUERY["source"], "trendsFilter": {"display": "BoxPlot"}},
                },
            ),
        ]
    )
    def test_only_trends_charts_are_probed(self, _name: str, query: dict) -> None:
        with patch(RUN_PATH) as run:
            assert empty_trends_chart_ids(MagicMock(id=1), [_chart(query)]) == []

        run.assert_not_called()
