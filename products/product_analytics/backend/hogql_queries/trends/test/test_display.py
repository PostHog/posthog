from unittest import TestCase

from parameterized import parameterized

from posthog.schema import ChartDisplayType

from products.product_analytics.backend.hogql_queries.trends.display import TrendsDisplay


class TestTrendsDisplay(TestCase):
    @parameterized.expand(
        [
            (ChartDisplayType.ACTIONS_PIE, True),
            (ChartDisplayType.ACTIONS_DONUT, True),
            (ChartDisplayType.ACTIONS_PROPORTION_BAR, True),
            (ChartDisplayType.ACTIONS_BAR_VALUE, True),
            (ChartDisplayType.ACTIONS_LINE_GRAPH, False),
            (ChartDisplayType.ACTIONS_BAR, False),
        ]
    )
    def test_is_total_value(self, display: ChartDisplayType, expected: bool) -> None:
        assert TrendsDisplay(display).is_total_value() is expected
