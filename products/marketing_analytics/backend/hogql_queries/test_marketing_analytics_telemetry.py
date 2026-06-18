from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DateRange, MarketingAnalyticsTableQuery

from products.marketing_analytics.backend.hogql_queries.marketing_analytics_table_query_runner import (
    MarketingAnalyticsTableQueryRunner,
)

TELEMETRY_PATH = (
    "products.marketing_analytics.backend.hogql_queries.marketing_analytics_base_query_runner.posthoganalytics.capture"
)


class TestMarketingAnalyticsTelemetry(BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.query = MarketingAnalyticsTableQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            properties=[],
        )

    def _runner(self) -> MarketingAnalyticsTableQueryRunner:
        return MarketingAnalyticsTableQueryRunner(query=self.query, team=self.team)

    @patch.object(MarketingAnalyticsTableQueryRunner, "_calculate")
    @patch(TELEMETRY_PATH)
    def test_emits_performed_event_on_success(self, mock_capture, mock_calculate):
        mock_calculate.return_value = MagicMock()
        runner = self._runner()

        runner.calculate()

        mock_capture.assert_called_once()
        kwargs = mock_capture.call_args.kwargs
        assert kwargs["event"] == "marketing analytics query performed"
        assert kwargs["distinct_id"] == str(self.team.uuid)
        props = kwargs["properties"]
        assert props["query_kind"] == "MarketingAnalyticsTableQuery"
        assert props["team_id"] == self.team.pk
        assert props["conversion_goals_count"] == 0
        assert props["has_compare"] is False
        assert isinstance(props["duration_ms"], (int, float))
        assert props["duration_ms"] >= 0
        assert "timings" in props
        assert "error_message" not in props

    @parameterized.expand(
        [
            ("short_message", ValueError, "boom", "boom"),
            ("long_message_is_truncated", RuntimeError, "x" * 5000, "x" * 500),
        ]
    )
    @patch.object(MarketingAnalyticsTableQueryRunner, "_calculate")
    @patch(TELEMETRY_PATH)
    def test_emits_failed_event_on_error_and_reraises(
        self, _name, exc_class, message, expected_message, mock_capture, mock_calculate
    ):
        mock_calculate.side_effect = exc_class(message)
        runner = self._runner()

        with self.assertRaises(exc_class):
            runner.calculate()

        mock_capture.assert_called_once()
        kwargs = mock_capture.call_args.kwargs
        assert kwargs["event"] == "marketing analytics query failed"
        props = kwargs["properties"]
        assert props["query_kind"] == "MarketingAnalyticsTableQuery"
        assert props["error_name"] == exc_class.__name__
        assert props["error_message"] == expected_message
        assert "timings" not in props

    @patch.object(MarketingAnalyticsTableQueryRunner, "_calculate")
    @patch(TELEMETRY_PATH)
    def test_capture_failure_does_not_break_query(self, mock_capture, mock_calculate):
        mock_capture.side_effect = Exception("analytics down")
        expected_response = MagicMock()
        mock_calculate.return_value = expected_response
        runner = self._runner()

        # Should not raise even though telemetry capture fails
        response = runner.calculate()

        assert response is expected_response
