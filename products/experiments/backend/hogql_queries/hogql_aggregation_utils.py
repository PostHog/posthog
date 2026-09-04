from typing import Optional, Union

from rest_framework.exceptions import ValidationError

from posthog.hogql import ast
from posthog.hogql.functions.mapping import HOGQL_AGGREGATIONS, HOGQL_CLICKHOUSE_FUNCTIONS, HOGQL_POSTHOG_FUNCTIONS
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import TraversingVisitor


def is_aggregation_function(function_name: str) -> bool:
    """Check if a function name is an aggregation function."""
    # Normalize function name to lowercase for case-insensitive comparison
    normalized_name = function_name.lower()

    # First check the dedicated HOGQL_AGGREGATIONS dictionary
    normalized_hogql_aggregations = [func.lower() for func in HOGQL_AGGREGATIONS.keys()]
    if normalized_name in normalized_hogql_aggregations:
        return True

    # Also check other function dictionaries for aggregate functions
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
    Extract the aggregation function, inner expression, parameters, and distinct flag from a HogQL expression.

    Args:
        hogql_expr: Either a HogQL expression string or an already parsed AST expression

    Returns:
        A tuple of (aggregation_function_name, inner_expression, params, distinct)
        - aggregation_function_name: The name of the aggregation function (e.g., "sum"), or None if not an aggregation
        - inner_expression: The inner expression AST node
        - params: List of parameter expressions for parametric aggregations (e.g., [0.90] for quantile), or None
        - distinct: Whether the aggregation uses DISTINCT (e.g., count(distinct ...))

    Examples:
        "sum(properties.revenue - properties.expense)" -> ("sum", <ArithmeticOperation node>, None, False)
        "quantile(0.90)(properties.margin)" -> ("quantile", <Field node>, [<Constant value=0.90>], False)
        "count(distinct properties.category)" -> ("count", <Field node>, None, True)
        "properties.revenue" -> (None, <Field node>, None, False)
        "count()" -> ("count", <Constant value=1>, None, False)
        "count(*)" -> ("count", <Constant value=1>, None, False)
    """
    # Parse the expression if it's a string
    if isinstance(hogql_expr, str):
        expr = parse_expr(hogql_expr)
    else:
        expr = hogql_expr

    # Check if the expression is a function call
    if isinstance(expr, ast.Call) and is_aggregation_function(expr.name):
        # It's an aggregation function
        aggregation_function = expr.name

        # Only name, args, params, and distinct survive the rebuild onto the per-row value column.
        # A FILTER (WHERE ...), ORDER BY, or WITHIN GROUP clause would be dropped, so the aggregate
        # would silently run over every row and report a wrong number. Reject it instead.
        if expr.filter_expr is not None or expr.order_by is not None or expr.within_group is not None:
            raise ValidationError(
                "HogQL metric expressions must use a plain aggregation, e.g. sum(properties.revenue). "
                "Clauses like FILTER (WHERE ...), ORDER BY, or WITHIN GROUP are not supported."
            )

        # Get the inner expression
        if expr.args and len(expr.args) > 0:
            # Only the first argument survives the rebuild onto the per-row value column.
            # A conditional aggregate like uniqExactIf(x, cond) would lose its condition and
            # then fail to compile, so reject it instead of dropping arguments silently.
            if len(expr.args) > 1:
                raise ValidationError(
                    "HogQL metric expressions must use a single-argument aggregation, e.g. sum(properties.revenue). "
                    "Conditional aggregations like uniqExactIf(x, cond) are not supported."
                )
            # Most aggregation functions take the expression as the first argument
            inner_expression = expr.args[0]
            # The parser stores a wildcard argument as Field(chain=["*"]). It is not a per-row
            # scalar, so splicing it into the value column breaks query construction. count(*)
            # means the same as count(), so map a lone wildcard to a per-row 1 for count, and
            # reject it for every other aggregation where a wildcard has no valid meaning.
            if isinstance(inner_expression, ast.Field) and inner_expression.chain == ["*"]:
                if aggregation_function.lower() == "count" and not expr.distinct:
                    inner_expression = ast.Constant(value=1)
                else:
                    raise ValidationError(
                        "HogQL metric expressions can only use a wildcard with count(*). "
                        "Aggregate a specific value instead, e.g. sum(properties.revenue)."
                    )
        else:
            # A missing argument is only valid for aggregates that support zero args, like count().
            # sum(), avg(), uniqExact(), and countIf() need one argument. HogQL rejects the empty
            # call, but the rebuild would aggregate a per-row constant 1 and report a wrong number,
            # so reject it instead.
            if not _aggregation_allows_no_args(aggregation_function):
                raise ValidationError(
                    f"The aggregation {aggregation_function}() must take an argument, e.g. sum(properties.revenue). "
                    "Only count() can be used without one."
                )
            # count() and other zero-argument aggregates aggregate a per-row 1.
            inner_expression = ast.Constant(value=1)

        # Extract parameters for parametric aggregations (e.g., quantile(0.90))
        params = expr.params if expr.params is not None else None
        distinct = bool(expr.distinct)

        return aggregation_function, inner_expression, params, distinct
    else:
        # Not an aggregation function - return the whole expression as the inner part
        return None, expr, None, False


# Registered in HOGQL_AGGREGATIONS for their rewriting behavior but compile to scalar
# expressions — not real aggregates (md5 -> hex(MD5(...))).
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
    """Check if an aggregation function requires numeric input (i.e. needs toFloat wrapping)."""
    return function_name.lower() not in _NON_NUMERIC_AGGREGATIONS


def _aggregation_allows_no_args(function_name: str) -> bool:
    """Whether an aggregation is valid with no arguments, e.g. count(). Reads the arity metadata."""
    normalized_name = function_name.lower()
    for name, meta in HOGQL_AGGREGATIONS.items():
        if name.lower() == normalized_name:
            return meta.min_args == 0
    for functions_dict in (HOGQL_CLICKHOUSE_FUNCTIONS, HOGQL_POSTHOG_FUNCTIONS):
        func_meta = functions_dict.get(normalized_name)
        if func_meta is not None:
            return func_meta.min_args == 0
    # An aggregate always resolves in one of the dicts above; keep the old fallback if it does not.
    return True


def build_aggregation_call(
    aggregation_function: str,
    inner_expr: ast.Expr,
    params: Optional[list[ast.Expr]] = None,
    distinct: bool = False,
) -> ast.Call:
    """
    Build an aggregation function call AST node.

    Args:
        aggregation_function: The aggregation function name (e.g., "sum", "quantile")
        inner_expr: The inner expression to aggregate
        params: Optional list of parameter expressions for parametric aggregations (e.g., [Constant(0.90)] for quantile)
        distinct: Whether to use DISTINCT (for functions that support it)

    Returns:
        An ast.Call node representing the aggregation

    Examples:
        build_aggregation_call("sum", Field(...)) -> Call(name="sum", args=[...])
        build_aggregation_call("quantile", Field(...), params=[Constant(0.90)]) -> Call(name="quantile", args=[...], params=[0.90])
    """
    return ast.Call(name=aggregation_function, args=[inner_expr], params=params, distinct=distinct)
