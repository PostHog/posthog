from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from products.experiments.backend.hogql_queries.hogql_aggregation_utils import (
    UnsupportedAggregationExpressionError,
    decompose_aggregation_expr,
    is_aggregation_function,
)


def _metric_events_column(index: int) -> ast.Expr:
    return ast.Field(chain=["metric_events", "value" if index == 0 else f"value_{index}"])


class TestHogQLAggregationUtils(BaseTest):
    @parameterized.expand(
        [
            ("sum", "sum", True),
            ("avg", "avg", True),
            ("count", "count", True),
            ("uppercase", "COUNT", True),
            ("plus", "plus", False),
            ("to_float", "toFloat", False),
            ("if", "if", False),
        ]
    )
    def test_is_aggregation_function(self, _: str, function_name: str, expected: bool):
        self.assertEqual(is_aggregation_function(function_name), expected)

    @parameterized.expand(
        [
            # A single top-level aggregation keeps the shape the query builder has always emitted.
            ("sum", "sum(properties.revenue)", ["properties.revenue"], "sum(toFloat(metric_events.value))"),
            (
                "sum_of_arithmetic",
                "sum(properties.revenue - properties.expense)",
                ["properties.revenue - properties.expense"],
                "sum(toFloat(metric_events.value))",
            ),
            ("count", "count()", ["1"], "count(metric_events.value)"),
            (
                "count_distinct",
                "count(distinct properties.category)",
                ["properties.category"],
                "count(distinct metric_events.value)",
            ),
            (
                "quantile",
                "quantile(0.9)(properties.margin)",
                ["properties.margin"],
                "quantile(0.9)(toFloat(metric_events.value))",
            ),
            # Arithmetic around an aggregation: the aggregation has to move up to the grouped
            # layer, leaving only its input behind as a per-event column.
            ("modulo", "count() % 2", ["1"], "count(metric_events.value) % 2"),
            ("multiply", "count() * 2", ["1"], "count(metric_events.value) * 2"),
            (
                "scaled_average",
                "avg(properties.x) * 100",
                ["properties.x"],
                "avg(toFloat(metric_events.value)) * 100",
            ),
            # Several aggregations each get their own input column.
            (
                "sum_over_count",
                "sum(properties.a) / count()",
                ["properties.a", "1"],
                "sum(toFloat(metric_events.value)) / count(metric_events.value_1)",
            ),
            (
                "conditional_sum",
                "sumIf(properties.a, properties.b > 1)",
                ["properties.a", "properties.b > 1"],
                "sumIf(toFloat(metric_events.value), metric_events.value_1)",
            ),
        ]
    )
    def test_decompose_aggregation_expr(
        self, _: str, expression: str, expected_columns: list[str], expected_aggregate: str
    ):
        decomposition = decompose_aggregation_expr(expression)

        self.assertEqual(decomposition.column_exprs, [parse_expr(column, start=None) for column in expected_columns])
        self.assertEqual(decomposition.build(_metric_events_column), parse_expr(expected_aggregate, start=None))

    def test_decompose_expression_without_aggregation_is_left_whole(self):
        decomposition = decompose_aggregation_expr("properties.revenue")

        self.assertFalse(decomposition.has_aggregation)
        self.assertEqual(decomposition.column_exprs, [])
        self.assertEqual(decomposition.template, parse_expr("properties.revenue", start=None))

    @parameterized.expand(
        [
            ("bare_aggregation", "sum(properties.revenue)", True),
            ("aggregation_with_arithmetic", "count() % 2", False),
            ("no_aggregation", "properties.revenue", False),
        ]
    )
    def test_is_bare_aggregation(self, _: str, expression: str, expected: bool):
        self.assertEqual(decompose_aggregation_expr(expression).is_bare_aggregation, expected)

    def test_decompose_rejects_nested_aggregations(self):
        with self.assertRaises(UnsupportedAggregationExpressionError):
            decompose_aggregation_expr("sum(count())")
