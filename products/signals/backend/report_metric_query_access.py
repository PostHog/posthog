"""Query shapes the report metric read policy can inspect for viewer access."""

from collections.abc import Callable, Mapping

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError

ORDINARY_PROPERTY_FILTER_TYPES = frozenset({"element", "event", "group", "person", "person_metadata", "session"})
MAX_PROPERTY_FILTER_DEPTH = 20
HOGQL_FILTER_EVENT_FIELDS = frozenset({"event", "timestamp", "distinct_id", "uuid", "elements_chain"})
HOGQL_BOOLEAN_CALLS = frozenset({"and", "or", "not"})
HOGQL_SAFE_MATH_CALLS = HOGQL_BOOLEAN_CALLS | frozenset(
    {
        "avg",
        "avgif",
        "coalesce",
        "count",
        "countif",
        "if",
        "max",
        "maxif",
        "min",
        "minif",
        "multiif",
        "nullif",
        "sum",
        "sumif",
        "tofloat",
        "toint",
        "uniq",
        "uniqif",
    }
)


def _hogql_field_allows_read(node: ast.Field) -> bool:
    return (len(node.chain) == 1 and node.chain[0] in HOGQL_FILTER_EVENT_FIELDS) or (
        len(node.chain) > 1 and node.chain[0] == "properties"
    )


def _hogql_call_allows_read(node: ast.Call, allowed_calls: frozenset[str], *, allow_distinct: bool) -> bool:
    return (
        node.name.lower() in allowed_calls
        and (allow_distinct or not node.distinct)
        and not node.params
        and not node.order_by
        and not node.within_group
        and not node.filter_expr
    )


def _is_non_distinct_count_star(node: ast.Call) -> bool:
    return (
        node.name.lower() == "count"
        and not node.distinct
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Field)
        and node.args[0].chain == ["*"]
    )


def _hogql_call_children(
    node: ast.Call, *, allowed_calls: frozenset[str], allow_distinct: bool
) -> tuple[ast.Expr, ...] | None:
    if not _hogql_call_allows_read(node, allowed_calls, allow_distinct=allow_distinct):
        return None
    if allow_distinct and _is_non_distinct_count_star(node):
        return ()
    return tuple(node.args)


def _hogql_leaf_allows_read(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) or (isinstance(node, ast.Field) and _hogql_field_allows_read(node))


def _hogql_node_children(
    node: ast.AST, *, allowed_calls: frozenset[str], allow_distinct: bool
) -> tuple[ast.Expr, ...] | None:
    if _hogql_leaf_allows_read(node):
        return ()
    if isinstance(node, ast.Not):
        return (node.expr,)
    if isinstance(node, ast.And | ast.Or | ast.Tuple | ast.Array):
        return tuple(node.exprs)
    if isinstance(node, ast.ArithmeticOperation):
        return (node.left, node.right)
    if isinstance(node, ast.CompareOperation):
        if node.op in {ast.CompareOperationOp.InCohort, ast.CompareOperationOp.NotInCohort}:
            return None
        return (node.left, node.right)
    if isinstance(node, ast.Call):
        return _hogql_call_children(node, allowed_calls=allowed_calls, allow_distinct=allow_distinct)
    return None


def _hogql_expr_allows_read(expression: object, *, allowed_calls: frozenset[str], allow_distinct: bool) -> bool:
    if not isinstance(expression, str) or not expression.strip():
        return False

    from posthog.hogql.parser import parse_expr  # noqa: PLC0415 — keeps the query parser off startup

    try:
        parsed: ast.AST = parse_expr(expression)
    except (BaseHogQLError, SyntaxError, ValueError, RecursionError):
        return False
    if allow_distinct and isinstance(parsed, ast.Alias):
        parsed = parsed.expr
    pending: list[tuple[ast.AST, int]] = [(parsed, 0)]

    # Shared snapshots cannot carry access to resources hidden behind subqueries or function calls.
    while pending:
        node, depth = pending.pop()
        if depth > MAX_PROPERTY_FILTER_DEPTH:
            return False
        children = _hogql_node_children(node, allowed_calls=allowed_calls, allow_distinct=allow_distinct)
        if children is None:
            return False
        pending.extend((child, depth + 1) for child in children)
    return True


def _hogql_filter_allows_read(expression: object) -> bool:
    return _hogql_expr_allows_read(expression, allowed_calls=HOGQL_BOOLEAN_CALLS, allow_distinct=False)


def hogql_math_allows_read(expression: object) -> bool:
    return _hogql_expr_allows_read(expression, allowed_calls=HOGQL_SAFE_MATH_CALLS, allow_distinct=True)


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
        if item.get("math") == "hogql" and not hogql_math_allows_read(item.get("math_hogql")):
            return False
        for field in ("properties", "fixedProperties"):
            if field in item and not property_filters_allow_read(item[field]):
                return False
    for field in ("properties", "fixedProperties"):
        if field in source and not property_filters_allow_read(source[field]):
            return False
    return conversion_goal_has_readable_shape(source.get("conversionGoal"))
