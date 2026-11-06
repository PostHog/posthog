"""Query shapes the report metric read policy can inspect for viewer access."""

from collections.abc import Callable, Mapping

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError

ORDINARY_PROPERTY_FILTER_TYPES = frozenset({"element", "event", "group", "person", "person_metadata", "session"})
MAX_PROPERTY_FILTER_DEPTH = 20
HOGQL_FILTER_EVENT_FIELDS = frozenset({"event", "timestamp", "distinct_id", "uuid", "elements_chain"})


def _hogql_filter_allows_read(expression: object) -> bool:
    if not isinstance(expression, str) or not expression.strip():
        return False

    from posthog.hogql.parser import parse_expr  # noqa: PLC0415 — keeps the query parser off startup

    try:
        pending = [(parse_expr(expression), 0)]
    except (BaseHogQLError, SyntaxError, ValueError, RecursionError):
        return False

    # Shared snapshots cannot carry access to resources hidden behind subqueries or function calls.
    while pending:
        node, depth = pending.pop()
        if depth > MAX_PROPERTY_FILTER_DEPTH:
            return False
        if isinstance(node, ast.And | ast.Or | ast.Tuple | ast.Array):
            pending.extend((child, depth + 1) for child in node.exprs)
        elif isinstance(node, ast.CompareOperation | ast.ArithmeticOperation):
            if isinstance(node, ast.CompareOperation) and node.op in {
                ast.CompareOperationOp.InCohort,
                ast.CompareOperationOp.NotInCohort,
            }:
                return False
            pending.extend(((node.left, depth + 1), (node.right, depth + 1)))
        elif isinstance(node, ast.Not):
            pending.append((node.expr, depth + 1))
        elif isinstance(node, ast.Call) and node.name.lower() in {"and", "or", "not"}:
            if node.params or node.distinct or node.order_by or node.within_group or node.filter_expr:
                return False
            pending.extend((child, depth + 1) for child in node.args)
        elif isinstance(node, ast.Field):
            if not (
                len(node.chain) == 1
                and node.chain[0] in HOGQL_FILTER_EVENT_FIELDS
                or len(node.chain) > 1
                and node.chain[0] == "properties"
            ):
                return False
        elif not isinstance(node, ast.Constant):
            return False
    return True


def property_filters_allow_read(filters: object, *, may_read_cohort: Callable[[int], bool] | None = None) -> bool:
    if filters is None:
        return True
    pending: list[tuple[object, int]]
    if isinstance(filters, list):
        pending = [(item, 0) for item in filters]
    elif isinstance(filters, Mapping) and filters.get("type") in ("AND", "OR"):
        pending = [(filters, 0)]
    else:
        return False

    while pending:
        item, depth = pending.pop()
        if not isinstance(item, Mapping) or depth > MAX_PROPERTY_FILTER_DEPTH:
            return False
        filter_type = item.get("type")
        if filter_type in ("AND", "OR"):
            values = item.get("values")
            if not isinstance(values, list):
                return False
            pending.extend((value, depth + 1) for value in values)
        elif filter_type == "cohort":
            cohort_id = item.get("value")
            if (
                item.get("key") != "id"
                or not isinstance(cohort_id, int)
                or isinstance(cohort_id, bool)
                or cohort_id <= 0
                or (may_read_cohort is not None and not may_read_cohort(cohort_id))
            ):
                return False
        elif filter_type == "hogql":
            if not _hogql_filter_allows_read(item.get("key")):
                return False
        elif not isinstance(filter_type, str) or filter_type not in ORDINARY_PROPERTY_FILTER_TYPES:
            return False
    return True


def conversion_goal_has_readable_shape(goal: object) -> bool:
    if goal is None:
        return True
    if not isinstance(goal, Mapping):
        return False
    if "actionId" in goal:
        action_id = goal["actionId"]
        return (
            set(goal) == {"actionId"}
            and isinstance(action_id, int)
            and not isinstance(action_id, bool)
            and action_id > 0
        )
    return (
        set(goal) == {"customEventName"}
        and isinstance(goal.get("customEventName"), str)
        and bool(goal["customEventName"])
    )


def query_filter_shape_allows_read(query: Mapping[str, object]) -> bool:
    source = query.get("source")
    if not isinstance(source, Mapping):
        return False
    series = source.get("series")
    if not isinstance(series, list) or any(not isinstance(item, Mapping) for item in series):
        return False
    for item in series:
        for field in ("properties", "fixedProperties"):
            if field in item and not property_filters_allow_read(item[field]):
                return False
    for field in ("properties", "fixedProperties"):
        if field in source and not property_filters_allow_read(source[field]):
            return False
    return conversion_goal_has_readable_shape(source.get("conversionGoal"))
