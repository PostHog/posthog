from posthog.test.base import BaseTest

from posthog.schema import EventsNode, ExperimentMeanMetric, ExperimentMetricMathType

from posthog.hogql import ast

from products.experiments.backend.hogql_queries.base_query_utils import get_metric_value


class TestHogQLAggregationIntegration(BaseTest):
    def test_get_metric_value_with_hogql_aggregation(self):
        """Test that get_metric_value correctly extracts inner expressions from HogQL aggregations."""

        # Test with aggregation function
        metric_with_agg = ExperimentMeanMetric(
            source=EventsNode(
                event="revenue_event",
                math=ExperimentMetricMathType.HOGQL,
                math_hogql="sum(properties.revenue - properties.expense)",
            )
        )

        result = get_metric_value(metric_with_agg)

        # Should return the inner expression (ArithmeticOperation), not the full sum() call
        self.assertIsInstance(result, ast.ArithmeticOperation)
        self.assertEqual(result.op, ast.ArithmeticOperationOp.Sub)  # type: ignore[attr-defined]

        # Test without aggregation function
        metric_without_agg = ExperimentMeanMetric(
            source=EventsNode(
                event="revenue_event", math=ExperimentMetricMathType.HOGQL, math_hogql="properties.revenue"
            )
        )

        result_no_agg = get_metric_value(metric_without_agg)

        # Should return the field expression directly
        self.assertIsInstance(result_no_agg, ast.Field)
        self.assertEqual(result_no_agg.chain, ["properties", "revenue"])  # type: ignore[attr-defined]
