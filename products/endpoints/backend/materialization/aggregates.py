from dataclasses import dataclass
from typing import Optional

from posthog.hogql import ast
from posthog.hogql.functions.aggregations import COMBINATORS
from posthog.hogql.functions.mapping import find_hogql_aggregation


@dataclass(frozen=True)
class AggregateReaggregation:
    """Defines how a base aggregate function is re-aggregated after bucketed materialization."""

    reaggregate_fn: str  # function to apply at read time (e.g., "sum" for count)


# Base functions that CAN be re-aggregated, and how.
# A combined function (e.g., sumIf) inherits from its base (sum).
REAGGREGATABLE_BASE_FUNCTIONS: dict[str, AggregateReaggregation] = {
    "count": AggregateReaggregation(reaggregate_fn="sum"),
    "sum": AggregateReaggregation(reaggregate_fn="sum"),
    "min": AggregateReaggregation(reaggregate_fn="min"),
    "max": AggregateReaggregation(reaggregate_fn="max"),
}


def _strip_combinators(func_name: str) -> str | None:
    """Strip ClickHouse combinator suffixes to find the base aggregate function.

    Uses the COMBINATORS registry from posthog.hogql.functions.aggregations.
    Returns the base function name (lowercased), or None if no match found.

    Examples:
        "sumIf" -> "sum"
        "countArrayIf" -> "count"
        "uniqMerge" -> "uniq" (but uniq is not in REAGGREGATABLE_BASE_FUNCTIONS)
        "count" -> "count"
    """
    name_lower = func_name.lower()
    if name_lower in REAGGREGATABLE_BASE_FUNCTIONS:
        return name_lower

    sorted_suffixes = sorted(COMBINATORS.keys(), key=len, reverse=True)

    def strip_recursive(name: str) -> str:
        for suffix in sorted_suffixes:
            if name.endswith(suffix.lower()) and len(name) > len(suffix):
                return strip_recursive(name[: -len(suffix)])
        return name

    base = strip_recursive(name_lower)
    return base if base != name_lower else None


def get_reaggregation(func_name: str) -> AggregateReaggregation | None:
    """Look up how to re-aggregate a (possibly combined) aggregate function.

    Returns AggregateReaggregation if the function can be re-aggregated, None otherwise.
    Handles ClickHouse combinators by stripping suffixes to find the base function.

    Examples:
        "count" -> AggregateReaggregation(reaggregate_fn="sum")
        "sumIf" -> AggregateReaggregation(reaggregate_fn="sum")
        "avg" -> None (not re-aggregatable)
        "uniqArrayIf" -> None (base "uniq" not in registry)
    """
    base = _strip_combinators(func_name)
    if base is None:
        return None
    return REAGGREGATABLE_BASE_FUNCTIONS.get(base)


def extract_aggregate_name(expr: ast.Expr) -> Optional[str]:
    """Extract the aggregate function name from a SELECT expression, if any.

    Handles two distinct-count syntaxes:
    - count(DISTINCT x): HogQL parses as Call(name="count", distinct=True) -> returns "countDistinct"
    - countDistinct(x): HogQL parses as Call(name="countDistinct") -> returns "countDistinct"

    Also recognizes functions with ClickHouse combinators (e.g., sumIf, countArrayIf)
    by checking if stripping combinators yields a known base aggregate function.
    """
    if isinstance(expr, ast.Alias):
        return extract_aggregate_name(expr.expr)
    if isinstance(expr, ast.Call):
        # count(DISTINCT x) and countDistinct(x) are both non-reaggregatable
        if expr.name == "count" and getattr(expr, "distinct", False):
            return "countDistinct"
        if expr.name == "countDistinct":
            return "countDistinct"

        if find_hogql_aggregation(expr.name):
            return expr.name

        # Recognize aggregate functions with combinators (e.g., sumIf, countArrayIf)
        # that aren't in the HogQL aggregation registry
        if _strip_combinators(expr.name) is not None:
            return expr.name
    return None
