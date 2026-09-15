from posthog.test.base import BaseTest

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import EventsNode, ExperimentDataWarehouseNode, ExperimentMeanMetric, ExperimentMetricMathType

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from products.experiments.backend.hogql_queries.base_query_utils import get_source_value_expr
from products.experiments.backend.hogql_queries.hogql_aggregation_utils import (
    build_aggregation_call,
    extract_aggregation_and_inner_expr,
    is_aggregation_function,
)


class TestHogQLAggregationUtils(BaseTest):
    def test_is_aggregation_function(self):
        """Test that we can identify aggregation functions."""

        # Test aggregation functions
        self.assertTrue(is_aggregation_function("sum"))
        self.assertTrue(is_aggregation_function("avg"))
        self.assertTrue(is_aggregation_function("count"))
        self.assertTrue(is_aggregation_function("min"))
        self.assertTrue(is_aggregation_function("max"))

        # Test case insensitive
        self.assertTrue(is_aggregation_function("SUM"))
        self.assertTrue(is_aggregation_function("AVG"))
        self.assertTrue(is_aggregation_function("COUNT"))

        # Test non-aggregation functions
        self.assertFalse(is_aggregation_function("plus"))
        self.assertFalse(is_aggregation_function("minus"))
        self.assertFalse(is_aggregation_function("toFloat"))
        self.assertFalse(is_aggregation_function("toString"))
        self.assertFalse(is_aggregation_function("if"))

    def test_extract_aggregation_and_inner_expr_with_aggregation(self):
        """Test extracting aggregation function and inner expression."""

        # Test sum with arithmetic operation
        aggregation, inner_expr, params, _ = extract_aggregation_and_inner_expr(
            "sum(properties.revenue - properties.expense)"
        )
        self.assertEqual(aggregation, "sum")
        self.assertIsInstance(inner_expr, ast.ArithmeticOperation)
        self.assertIsNone(params)  # Non-parametric aggregation

        # Test avg with field
        aggregation, inner_expr, params, _ = extract_aggregation_and_inner_expr("avg(properties.price)")
        self.assertEqual(aggregation, "avg")
        self.assertIsInstance(inner_expr, ast.Field)
        self.assertIsNone(params)

        # Test count with no arguments
        aggregation, inner_expr, params, _ = extract_aggregation_and_inner_expr("count()")
        self.assertEqual(aggregation, "count")
        self.assertIsInstance(inner_expr, ast.Constant)
        self.assertEqual(inner_expr.value, 1)  # type: ignore[attr-defined]
        self.assertIsNone(params)

        # Test min with field
        aggregation, inner_expr, params, _ = extract_aggregation_and_inner_expr("min(properties.score)")
        self.assertEqual(aggregation, "min")
        self.assertIsInstance(inner_expr, ast.Field)
        self.assertIsNone(params)

        # Test max with field
        aggregation, inner_expr, params, _ = extract_aggregation_and_inner_expr("max(properties.value)")
        self.assertEqual(aggregation, "max")
        self.assertIsInstance(inner_expr, ast.Field)
        self.assertIsNone(params)

    def test_extract_aggregation_and_inner_expr_without_aggregation(self):
        """Test extracting from non-aggregation expressions."""

        # Test simple field
        aggregation, inner_expr, params, _ = extract_aggregation_and_inner_expr("properties.revenue")
        self.assertIsNone(aggregation)
        self.assertIsInstance(inner_expr, ast.Field)
        self.assertIsNone(params)

        # Test arithmetic operation
        aggregation, inner_expr, params, _ = extract_aggregation_and_inner_expr("1 + 2")
        self.assertIsNone(aggregation)
        self.assertIsInstance(inner_expr, ast.ArithmeticOperation)
        self.assertIsNone(params)

        # Test function call that's not an aggregation
        aggregation, inner_expr, params, _ = extract_aggregation_and_inner_expr("toFloat(properties.value)")
        self.assertIsNone(aggregation)
        self.assertIsInstance(inner_expr, ast.Call)
        self.assertIsNone(params)

    def test_extract_aggregation_and_inner_expr_with_ast_input(self):
        """Test that the function works with AST nodes as input."""

        # Parse expression first
        expr = parse_expr("sum(properties.revenue)")

        # Extract from AST
        aggregation, inner_expr, params, _ = extract_aggregation_and_inner_expr(expr)
        self.assertEqual(aggregation, "sum")
        self.assertIsInstance(inner_expr, ast.Field)
        self.assertIsNone(params)

    def test_build_aggregation_call(self):
        """Test building aggregation calls."""

        inner_expr = parse_expr("properties.revenue - properties.expense")

        # Test building a sum aggregation
        agg_call = build_aggregation_call("sum", inner_expr)

        self.assertIsInstance(agg_call, ast.Call)
        self.assertEqual(agg_call.name, "sum")
        self.assertEqual(len(agg_call.args), 1)
        self.assertEqual(agg_call.args[0], inner_expr)
        self.assertFalse(agg_call.distinct)

        # Test building with distinct
        agg_call_distinct = build_aggregation_call("count", inner_expr, distinct=True)
        self.assertTrue(agg_call_distinct.distinct)

    def test_extract_aggregation_with_params(self):
        """Test that parametric aggregations preserve their parameters."""

        # Test quantile with single parameter
        agg, inner, params, _ = extract_aggregation_and_inner_expr("quantile(0.90)(properties.margin)")
        self.assertEqual(agg, "quantile")
        self.assertIsInstance(inner, ast.Field)
        self.assertIsNotNone(params)
        assert params is not None  # for mypy
        self.assertEqual(len(params), 1)
        self.assertIsInstance(params[0], ast.Constant)
        assert isinstance(params[0], ast.Constant)  # for mypy
        self.assertEqual(params[0].value, 0.90)

        # Test quantile with different level
        agg, inner, params, _ = extract_aggregation_and_inner_expr("quantile(0.50)(properties.value)")
        self.assertEqual(agg, "quantile")
        self.assertIsNotNone(params)
        assert params is not None  # for mypy
        assert isinstance(params[0], ast.Constant)  # for mypy
        self.assertEqual(params[0].value, 0.50)

        # Test non-parametric aggregation returns None for params
        agg, inner, params, _ = extract_aggregation_and_inner_expr("sum(properties.revenue)")
        self.assertEqual(agg, "sum")
        self.assertIsNone(params)

    def test_build_aggregation_call_with_params(self):
        """Test that build_aggregation_call handles parametric functions."""

        inner_expr = parse_expr("properties.value")
        params: list[ast.Expr] = [ast.Constant(value=0.90)]

        # Build quantile with parameter
        result = build_aggregation_call("quantile", inner_expr, params=params)

        # Should produce: quantile(0.90)(properties.value)
        self.assertIsInstance(result, ast.Call)
        self.assertEqual(result.name, "quantile")
        self.assertIsNotNone(result.params)
        assert result.params is not None  # for mypy
        self.assertEqual(len(result.params), 1)
        assert isinstance(result.params[0], ast.Constant)  # for mypy
        self.assertEqual(result.params[0].value, 0.90)
        self.assertEqual(result.args[0], inner_expr)

        # Test building without params (non-parametric aggregation)
        result_no_params = build_aggregation_call("sum", inner_expr, params=None)
        self.assertIsInstance(result_no_params, ast.Call)
        self.assertEqual(result_no_params.name, "sum")
        self.assertIsNone(result_no_params.params)

    def test_source_value_expr_with_hogql_aggregation(self):
        # Test with aggregation function
        metric_with_agg = ExperimentMeanMetric(
            source=EventsNode(
                event="revenue_event",
                math=ExperimentMetricMathType.HOGQL,
                math_hogql="sum(properties.revenue - properties.expense)",
            )
        )

        result = get_source_value_expr(metric_with_agg.source)

        # Should return the inner expression (ArithmeticOperation), not the full sum() call
        self.assertIsInstance(result, ast.ArithmeticOperation)
        self.assertEqual(result.op, ast.ArithmeticOperationOp.Sub)  # type: ignore[attr-defined]

        # Test without aggregation function
        metric_without_agg = ExperimentMeanMetric(
            source=EventsNode(
                event="revenue_event", math=ExperimentMetricMathType.HOGQL, math_hogql="properties.revenue"
            )
        )

        result_no_agg = get_source_value_expr(metric_without_agg.source)

        # Should return the field expression directly
        self.assertIsInstance(result_no_agg, ast.Field)
        self.assertEqual(result_no_agg.chain, ["properties", "revenue"])  # type: ignore[attr-defined]

    @parameterized.expand(
        [
            ("division", "sum(properties.revenue) / count()"),
            ("addition", "sum(properties.a) + sum(properties.b)"),
            ("wrapped", "toFloat(sum(properties.revenue))"),
            ("nested", "avg(sum(properties.revenue))"),
        ]
    )
    def test_rejects_compound_aggregate_expressions(self, _name: str, expr: str):
        # The extracted value expression is evaluated per row; aggregates left inside it
        # (compound or nested) would fail in ClickHouse with NOT_AN_AGGREGATE.
        metric = ExperimentMeanMetric(
            source=EventsNode(event="revenue_event", math=ExperimentMetricMathType.HOGQL, math_hogql=expr)
        )
        with self.assertRaises(ValidationError):
            get_source_value_expr(metric.source)

    def test_allows_scalar_md5_despite_registry_quirk(self):
        # md5 lives in HOGQL_AGGREGATIONS for its rewriting but compiles to a scalar —
        # it must not trip the aggregate check.
        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="revenue_event",
                math=ExperimentMetricMathType.HOGQL,
                math_hogql="count(distinct md5(properties.user))",
            )
        )
        result = get_source_value_expr(metric.source)
        self.assertIsInstance(result, ast.Call)
        self.assertEqual(result.name, "md5")  # type: ignore[attr-defined]

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

    @parameterized.expand(
        [
            ("plain_column", "amount"),
            ("scalar_md5", "md5(user_id)"),
        ]
    )
    def test_allows_per_row_data_warehouse_math_property(self, _name: str, math_property: str):
        source = ExperimentDataWarehouseNode(
            table_name="payments",
            events_join_key="person_id",
            data_warehouse_join_key="user_id",
            timestamp_field="ts",
            math_property=math_property,
        )
        get_source_value_expr(source)
