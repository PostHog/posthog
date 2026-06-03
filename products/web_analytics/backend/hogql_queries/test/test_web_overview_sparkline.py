from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.schema import CustomEventConversionGoal, DateRange, WebOverviewQuery

from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner
from products.web_analytics.backend.hogql_queries.web_overview_lazy_precompute import rows_to_sparkline_series

LAZY_MODULE = "products.web_analytics.backend.hogql_queries.web_overview"


class TestWebOverviewSparkline(ClickhouseTestMixin, APIBaseTest):
    def _runner(self, *, include_sparkline=True, conversion_goal=None):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-03"),
            properties=[],
            includeSparkline=include_sparkline,
            conversionGoal=conversion_goal,
        )
        return WebOverviewQueryRunner(team=self.team, query=query)

    def test_rows_to_sparkline_series_maps_columns_and_transforms(self):
        # Rows: [bucket, visitors, views, sessions, session_duration, bounce_rate], two daily buckets.
        rows = [
            ["2024-01-01", 2, 3, 2, 120.0, 0.5],
            ["2024-01-02", 1, 1, 1, 60.0, 1.0],
        ]
        series = rows_to_sparkline_series(rows, unsample=lambda x: x)

        assert series["visitors"] == [2, 1]
        assert series["views"] == [3, 1]
        assert series["sessions"] == [2, 1]
        assert series["session duration"] == [120.0, 60.0]
        # Bounce rate is surfaced as a percentage.
        assert series["bounce rate"] == [50.0, 100.0]

    def test_rows_to_sparkline_series_unsamples_counts_only(self):
        rows = [["2024-01-01", 5, 10, 5, 30.0, 0.2]]
        series = rows_to_sparkline_series(rows, unsample=lambda x: x * 10)

        assert series["visitors"] == [50]
        assert series["views"] == [100]
        assert series["sessions"] == [50]
        # Averages are not unsampled.
        assert series["session duration"] == [30.0]
        assert series["bounce rate"] == [20.0]

    def test_no_sparkline_when_not_requested(self):
        assert self._runner(include_sparkline=False).get_lazy_precomputed_sparkline() is None

    def test_no_sparkline_for_conversion_goal(self):
        runner = self._runner(conversion_goal=CustomEventConversionGoal(customEventName="signup"))
        assert runner.get_lazy_precomputed_sparkline() is None

    def test_no_sparkline_when_lazy_not_eligible(self):
        runner = self._runner()
        with patch(f"{LAZY_MODULE}.can_use_lazy_precompute", return_value=False):
            assert runner.get_lazy_precomputed_sparkline() is None

    def test_sparkline_read_when_lazy_eligible(self):
        runner = self._runner()
        fake_series = {"visitors": [2, 1], "views": [3, 1], "sessions": [2, 1]}
        with (
            patch(f"{LAZY_MODULE}.can_use_lazy_precompute", return_value=True),
            patch(f"{LAZY_MODULE}.execute_lazy_precomputed_sparkline", return_value=fake_series) as mock_read,
        ):
            assert runner.get_lazy_precomputed_sparkline() == fake_series
            mock_read.assert_called_once_with(runner)

    def test_attach_sparkline_sets_series_on_matching_items(self):
        runner = self._runner()
        results = [
            {"key": "visitors", "kind": "unit", "value": 3},
            {"key": "views", "kind": "unit", "value": 4},
        ]
        with patch.object(runner, "get_lazy_precomputed_sparkline", return_value={"visitors": [2, 1]}):
            attached = runner._attach_sparkline(results)

        assert attached[0]["series"] == [2, 1]
        assert "series" not in attached[1]
