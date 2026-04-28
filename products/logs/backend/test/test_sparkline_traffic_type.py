from posthog.schema import LogsSparklineBreakdownBy

from posthog.hogql import ast

from products.logs.backend.sparkline_query_runner import BREAKDOWN_DB_FIELD, _breakdown_expr


class TestBreakdownExpr:
    def test_severity_returns_field(self):
        expr = _breakdown_expr(LogsSparklineBreakdownBy.SEVERITY)
        assert isinstance(expr, ast.Field)
        assert expr.chain == ["severity_text"]

    def test_service_returns_field(self):
        expr = _breakdown_expr(LogsSparklineBreakdownBy.SERVICE)
        assert isinstance(expr, ast.Field)
        assert expr.chain == ["service_name"]

    def test_traffic_type_returns_if_expression(self):
        expr = _breakdown_expr(LogsSparklineBreakdownBy.TRAFFIC_TYPE)
        assert isinstance(expr, ast.Call)
        assert expr.name == "if"

    def test_traffic_type_uses_multiMatchAnyIndex(self):
        expr = _breakdown_expr(LogsSparklineBreakdownBy.TRAFFIC_TYPE)
        comparison = expr.args[0]
        assert isinstance(comparison, ast.CompareOperation)
        assert isinstance(comparison.left, ast.Call)
        assert comparison.left.name == "multiMatchAnyIndex"

    def test_traffic_type_default_is_regular(self):
        expr = _breakdown_expr(LogsSparklineBreakdownBy.TRAFFIC_TYPE)
        default = expr.args[1]
        assert isinstance(default, ast.Constant)
        assert default.value == "Regular"

    def test_all_simple_breakdowns_in_field_map(self):
        for breakdown in [LogsSparklineBreakdownBy.SEVERITY, LogsSparklineBreakdownBy.SERVICE]:
            assert breakdown in BREAKDOWN_DB_FIELD
