from posthog.test.base import BaseTest

from rest_framework.exceptions import ValidationError

from posthog.schema import EventsNode, ExperimentDataWarehouseNode, ExperimentMeanMetric, ExperimentMetricMathType

from posthog.hogql import ast

from products.experiments.backend.hogql_queries.base_query_utils import get_metric_value, get_source_value_expr


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

    def test_rejects_compound_aggregate_expressions(self):
        # The extracted value expression is evaluated per row; aggregates left inside it
        # (compound or nested) would fail in ClickHouse with NOT_AN_AGGREGATE.
        for expr in [
            "sum(properties.revenue) / count()",
            "sum(properties.a) + sum(properties.b)",
            "toFloat(sum(properties.revenue))",
            "avg(sum(properties.revenue))",
        ]:
            metric = ExperimentMeanMetric(
                source=EventsNode(event="revenue_event", math=ExperimentMetricMathType.HOGQL, math_hogql=expr)
            )
            with self.assertRaises(ValidationError, msg=expr):
                get_metric_value(metric)

    def test_rejects_aggregates_in_data_warehouse_math_property(self):
        source = ExperimentDataWarehouseNode(
            table_name="payments",
            events_join_key="person_id",
            data_warehouse_join_key="user_id",
            timestamp_field="ts",
            math_property="sum(amount)",
        )
        with self.assertRaises(ValidationError):
            get_source_value_expr(source)

    def test_allows_plain_data_warehouse_math_property(self):
        source = ExperimentDataWarehouseNode(
            table_name="payments",
            events_join_key="person_id",
            data_warehouse_join_key="user_id",
            timestamp_field="ts",
            math_property="amount",
        )
        result = get_source_value_expr(source)
        self.assertIsInstance(result, ast.Field)
