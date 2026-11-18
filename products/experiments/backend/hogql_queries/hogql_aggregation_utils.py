from typing import Optional, Union

from posthog.hogql import ast
from posthog.hogql.functions.mapping import HOGQL_AGGREGATIONS, HOGQL_CLICKHOUSE_FUNCTIONS, HOGQL_POSTHOG_FUNCTIONS
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import TraversingVisitor


def is_aggregation_function(function_name: str) -> bool:
    normalized_name = function_name.lower()

    normalized_hogql_aggregations = [func.lower() for func in HOGQL_AGGREGATIONS.keys()]
    if normalized_name in normalized_hogql_aggregations:
        return True

    for functions_dict in [HOGQL_CLICKHOUSE_FUNCTIONS, HOGQL_POSTHOG_FUNCTIONS]:
        if normalized_name in functions_dict:
            func_meta = functions_dict[normalized_name]
            if hasattr(func_meta, "aggregate") and func_meta.aggregate:
                return True

    return False


def extract_aggregation_and_inner_expr(
    hogql_expr: Union[str, ast.Expr],
) -> tuple[Optional[str], ast.Expr, Optional[list[ast.Expr]], bool]:
    """
    Returns (aggregation_function_name, inner_expression, params, distinct). The
    function name is None when the top-level expression is not an aggregation.

    Examples:
        "sum(properties.revenue - properties.expense)" -> ("sum", <ArithmeticOperation node>, None, False)
        "quantile(0.90)(properties.margin)" -> ("quantile", <Field node>, [<Constant value=0.90>], False)
        "count(distinct properties.category)" -> ("count", <Field node>, None, True)
        "properties.revenue" -> (None, <Field node>, None, False)
        "count()" -> ("count", <Constant value=1>, None, False)
    """
    if isinstance(hogql_expr, str):
        expr = parse_expr(hogql_expr)
    else:
        expr = hogql_expr

    if isinstance(expr, ast.Call) and is_aggregation_function(expr.name):
        aggregation_function = expr.name

        if expr.args and len(expr.args) > 0:
            inner_expression = expr.args[0]
        else:
            # count() has no argument, so aggregate a constant 1 per row.
            inner_expression = ast.Constant(value=1)

        params = expr.params if expr.params is not None else None
        distinct = bool(expr.distinct)

        return aggregation_function, inner_expression, params, distinct
    else:
        return None, expr, None, False


# Registered in HOGQL_AGGREGATIONS for their rewriting behavior, but they compile to
# scalar expressions and are not real aggregates (md5 -> hex(MD5(...))).
_SCALAR_REGISTRY_QUIRKS = frozenset({"md5"})


class _AggregationFinder(TraversingVisitor):
    def __init__(self):
        super().__init__()
        self.found = False

    def visit_call(self, node: ast.Call):
        if node.name.lower() not in _SCALAR_REGISTRY_QUIRKS and is_aggregation_function(node.name):
            self.found = True
            return
        for arg in node.args:
            self.visit(arg)
        for param in node.params or []:
            self.visit(param)


def contains_aggregation(expr: ast.Expr) -> bool:
    """Whether a real aggregate call appears anywhere in the expression."""
    finder = _AggregationFinder()
    finder.visit(expr)
    return finder.found


_NON_NUMERIC_AGGREGATIONS = frozenset(
    {
        "uniq",
        "uniqif",
        "uniqexact",
        "uniqexactif",
        "count",
        "countif",
    }
)


def aggregation_needs_numeric_input(function_name: str) -> bool:
    """Whether the aggregation needs a toFloat() around its input."""
    return function_name.lower() not in _NON_NUMERIC_AGGREGATIONS


def build_aggregation_call(
    aggregation_function: str,
    inner_expr: ast.Expr,
    params: Optional[list[ast.Expr]] = None,
    distinct: bool = False,
) -> ast.Call:
    return ast.Call(name=aggregation_function, args=[inner_expr], params=params, distinct=distinct)
