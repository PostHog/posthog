from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Optional, Union

from posthog.hogql import ast
from posthog.hogql.functions.mapping import HOGQL_AGGREGATIONS, HOGQL_CLICKHOUSE_FUNCTIONS, HOGQL_POSTHOG_FUNCTIONS
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import has_aggregation
from posthog.hogql.visitor import CloningVisitor


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


def build_aggregation_call(
    aggregation_function: str,
    inner_expr: Union[ast.Expr, list[ast.Expr]],
    params: Optional[list[ast.Expr]] = None,
    distinct: bool = False,
) -> ast.Call:
    """
    Build an aggregation function call AST node.

    Args:
        aggregation_function: The aggregation function name (e.g., "sum", "quantile")
        inner_expr: The inner expression to aggregate, or the full argument list
        params: Optional list of parameter expressions for parametric aggregations (e.g., [Constant(0.90)] for quantile)
        distinct: Whether to use DISTINCT (for functions that support it)

    Returns:
        An ast.Call node representing the aggregation

    Examples:
        build_aggregation_call("sum", Field(...)) -> Call(name="sum", args=[...])
        build_aggregation_call("quantile", Field(...), params=[Constant(0.90)]) -> Call(name="quantile", args=[...], params=[0.90])
    """
    args = inner_expr if isinstance(inner_expr, list) else [inner_expr]
    return ast.Call(name=aggregation_function, args=args, params=params, distinct=distinct)


# Marker field name that stands in for an aggregation call while an expression is decomposed.
AGGREGATION_PLACEHOLDER_PREFIX = "__experiment_aggregation_"


def value_column_name(index: int, base_column_name: str = "value") -> str:
    """Name of the event-CTE column carrying aggregation input ``index``.

    Input 0 keeps the unsuffixed name so everything built around the primary value column
    (winsorization, CUPED, breakdowns, the data warehouse joins) is untouched by this.
    """
    return base_column_name if index == 0 else f"{base_column_name}_{index}"


class UnsupportedAggregationExpressionError(ValueError):
    """A math expression the experiment query builder can't split into per-event and per-entity halves."""


@dataclass(frozen=True)
class HoistedAggregation:
    """One aggregation call lifted out of a math expression, pointing at the columns it consumes."""

    function: str
    arg_indices: list[int]
    params: Optional[list[ast.Expr]] = None
    distinct: bool = False


@dataclass
class AggregationDecomposition:
    """A math expression split across the two layers of an experiment query.

    Experiment queries scan events into a ``metric_events`` CTE with no GROUP BY, then aggregate
    per entity in ``entity_metrics``. An expression like ``count() % 2`` therefore can't be
    evaluated in one place: ``count`` belongs to the grouped layer, and whatever it counts belongs
    to the scan. Decomposition splits it — ``column_exprs`` are the per-event values to project,
    and :meth:`build` rebuilds the outer expression with each aggregation applied to those columns.

    ``count() % 2`` yields ``column_exprs=[1]`` and rebuilds to ``count(<col 0>) % 2``.
    ``sum(properties.revenue)`` yields ``column_exprs=[properties.revenue]`` and rebuilds to
    ``sum(<col 0>)``, matching what the single-aggregation path has always produced.
    """

    template: ast.Expr
    column_exprs: list[ast.Expr] = field(default_factory=list)
    aggregations: list[HoistedAggregation] = field(default_factory=list)

    @property
    def has_aggregation(self) -> bool:
        return bool(self.aggregations)

    @property
    def is_bare_aggregation(self) -> bool:
        """Whether the whole expression is a single aggregation call with nothing wrapped around it."""
        return (
            len(self.aggregations) == 1
            and isinstance(self.template, ast.Field)
            and self.template.chain == [f"{AGGREGATION_PLACEHOLDER_PREFIX}0"]
        )

    def build(self, column_ref: Callable[[int], ast.Expr]) -> ast.Expr:
        """Rebuild the expression, resolving each hoisted aggregation against its projected columns.

        ``column_ref`` maps a ``column_exprs`` index to the expression that reads it back in the
        grouped layer — usually ``metric_events.value``, or a conversion-window-masked variant of it.
        """
        replacements: dict[str, ast.Expr] = {}
        for index, aggregation in enumerate(self.aggregations):
            args = [column_ref(column_index) for column_index in aggregation.arg_indices]
            if args and aggregation_needs_numeric_input(aggregation.function):
                args[0] = ast.Call(name="toFloat", args=[args[0]])
            replacements[f"{AGGREGATION_PLACEHOLDER_PREFIX}{index}"] = build_aggregation_call(
                aggregation.function, args, params=aggregation.params, distinct=aggregation.distinct
            )
        return _AggregationPlaceholderResolver(replacements).visit(self.template)


class _AggregationHoister(CloningVisitor):
    """Replaces every aggregation call with a placeholder, collecting its arguments as columns."""

    def __init__(self) -> None:
        # The rebuilt expression mixes user nodes with generated ones, so source offsets no longer
        # point at anything meaningful.
        super().__init__(clear_locations=True)
        self.column_exprs: list[ast.Expr] = []
        self.aggregations: list[HoistedAggregation] = []

    def visit_select_query(self, node: ast.SelectQuery) -> ast.Expr:
        # Aggregations inside a subquery belong to that subquery, so leave it untouched.
        return node

    def visit_call(self, node: ast.Call) -> ast.Expr:
        if not is_aggregation_function(node.name):
            return super().visit_call(node)

        for arg in node.args:
            if has_aggregation(arg):
                raise UnsupportedAggregationExpressionError(f"'{node.name}' can't be applied to another aggregation.")

        # `count()` still needs a column to count: the projected constant is NULL on the padding row
        # a LEFT JOIN produces for an entity with no events, so those entities count 0 rather than 1.
        args: list[ast.Expr] = [self.visit(arg) for arg in node.args] or [ast.Constant(value=1)]

        first_column_index = len(self.column_exprs)
        self.column_exprs.extend(args)
        placeholder = f"{AGGREGATION_PLACEHOLDER_PREFIX}{len(self.aggregations)}"
        self.aggregations.append(
            HoistedAggregation(
                function=node.name,
                arg_indices=list(range(first_column_index, len(self.column_exprs))),
                params=[self.visit(param) for param in node.params] if node.params is not None else None,
                distinct=bool(node.distinct),
            )
        )
        return ast.Field(chain=[placeholder])


class _AggregationPlaceholderResolver(CloningVisitor):
    def __init__(self, replacements: dict[str, ast.Expr]) -> None:
        super().__init__(clear_locations=True)
        self.replacements = replacements

    def visit_field(self, node: ast.Field) -> ast.Expr:
        if len(node.chain) == 1 and isinstance(node.chain[0], str) and node.chain[0] in self.replacements:
            return self.replacements[node.chain[0]]
        return super().visit_field(node)


def unsupported_sql_expression_message(reason: object) -> str:
    return (
        f"This SQL expression can't be used as a metric. {reason} "
        "Aggregate event values instead, for example sum(properties.revenue) / count()."
    )


def unparseable_sql_expression_message(reason: object) -> str:
    return f"Couldn't read the SQL expression for this metric. Check its syntax: {reason}"


def decompose_aggregation_expr(hogql_expr: Union[str, ast.Expr]) -> AggregationDecomposition:
    """Split a metric math expression into per-event columns plus the aggregate expression on top.

    Raises :class:`UnsupportedAggregationExpressionError` when the expression can't be split, which
    today means one aggregation nested inside another.
    """
    expr = parse_expr(hogql_expr) if isinstance(hogql_expr, str) else hogql_expr

    hoister = _AggregationHoister()
    template = hoister.visit(expr)
    return AggregationDecomposition(
        template=template,
        column_exprs=hoister.column_exprs,
        aggregations=hoister.aggregations,
    )
