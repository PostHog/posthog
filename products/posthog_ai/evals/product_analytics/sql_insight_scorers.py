"""Scorers for the SQL insights an agent saves.

A saved SQL insight runs its own query text. A dashboard or insight date range reaches that
text only through a ``{filters}`` placeholder, so a query with a hard-coded window ignores the
date picker. A SQL chart also draws its rows in query order, so a time series needs an ascending
``ORDER BY`` on its time column, or the newest bucket can show on the left.

Each scorer grades the most recent successful ``insight-create`` or ``insight-update`` call that
holds a ``HogQLQuery``.
"""

from __future__ import annotations

import re
import json
from typing import Any

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.functions.mapping import find_hogql_aggregation
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import TraversingVisitor

from products.posthog_ai.eval_harness.log_parser import ToolCall
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer
from products.posthog_ai.evals.cli_mcp.scorers import tool_output_text
from products.posthog_ai.evals.product_analytics.scorers import _saved_query, parser_for

_SAVE_TOOLS = ("insight-create", "insight-update")
_CLOCK_FUNCTIONS = frozenset({"now", "now64", "today", "yesterday"})
_TIME_BUCKET_FUNCTIONS = frozenset({"todate", "todatetime", "tomonday", "datetrunc", "date_trunc"})
_RANGE_OPS = frozenset(
    {
        ast.CompareOperationOp.Gt,
        ast.CompareOperationOp.GtEq,
        ast.CompareOperationOp.Lt,
        ast.CompareOperationOp.LtEq,
    }
)
_OUTPUT_ID_RE = re.compile(r"^(?:id|short_id):\s*(\S+)\s*$", re.MULTILINE)


def _saved_sql_calls(calls: list[ToolCall]) -> list[tuple[ToolCall, dict[str, Any]]]:
    saved: list[tuple[ToolCall, dict[str, Any]]] = []
    for call in calls:
        answer = _saved_query(call)
        if answer is not None and answer[0] == "execute-sql":
            saved.append((call, answer[1]))
    return saved


def _last_saved_sql(output: dict | None) -> dict[str, Any] | None:
    parser = parser_for(output)
    if parser is None:
        return None
    saved = _saved_sql_calls(parser.get_tool_calls())
    return saved[-1][1] if saved else None


def _insight_ids(call: ToolCall) -> set[str]:
    """The numeric id and short id of the insight that a save call wrote."""
    if call.name == "insight-update":
        return {str(call.input["id"])} if call.input.get("id") is not None else set()
    text = tool_output_text(call.output)
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return set(_OUTPUT_ID_RE.findall(text))
    if not isinstance(payload, dict):
        return set()
    return {str(payload[key]) for key in ("id", "short_id") if payload.get(key) is not None}


def _parse(source: dict[str, Any]) -> ast.SelectQuery | ast.SelectSetQuery | None:
    text = source.get("query")
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return parse_select(text)
    except BaseHogQLError:
        return None


def _hogql_text(node: ast.Expr) -> str:
    """The expression as HogQL for score metadata.

    The printer cannot print a placeholder such as ``{filters.dateRange.from}``, and a failed
    print must not turn a graded case into a scorer error.
    """
    try:
        return node.to_hogql()
    except BaseHogQLError:
        return f"<{type(node).__name__} with a placeholder>"


def _outer_select(node: ast.SelectQuery | ast.SelectSetQuery) -> ast.SelectQuery:
    while isinstance(node, ast.SelectSetQuery):
        node = node.initial_select_query
    return node


class _Calls(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()
        self.raw_names: set[str] = set()
        self.fields: set[str] = set()

    def visit_call(self, node: ast.Call) -> None:
        self.names.add(node.name.lower())
        self.raw_names.add(node.name)
        super().visit_call(node)

    def visit_field(self, node: ast.Field) -> None:
        if node.chain:
            self.fields.add(str(node.chain[-1]).lower())
        super().visit_field(node)


def _calls_in(node: ast.Expr) -> _Calls:
    found = _Calls()
    found.visit(node)
    return found


class _DateLiterals(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and node.value[:4].isdigit():
            self.found = True


def _has_date_literal(node: ast.Expr) -> bool:
    literals = _DateLiterals()
    literals.visit(node)
    return literals.found


class _HardCodedWindows(TraversingVisitor):
    """Range comparisons against the clock or a date literal, such as ``timestamp >= now() - INTERVAL 7 DAY``.

    A literal counts inside a conversion too, such as ``timestamp >= toDateTime('2026-01-01')``.
    """

    def __init__(self) -> None:
        super().__init__()
        self.found: list[str] = []

    def _check(self, node: ast.Expr, bounds: list[ast.Expr]) -> None:
        if any(_calls_in(bound).names & _CLOCK_FUNCTIONS or _has_date_literal(bound) for bound in bounds):
            self.found.append(_hogql_text(node))

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        if node.op in _RANGE_OPS:
            self._check(node, [node.left, node.right])
        super().visit_compare_operation(node)

    def visit_between_expr(self, node: ast.BetweenExpr) -> None:
        self._check(node, [node.low, node.high])
        super().visit_between_expr(node)


class _DateBoundingPlaceholders(TraversingVisitor):
    """Finds a ``filters`` placeholder that adds a date predicate.

    ``{filters}``, ``{filters.dateRange.from}``, ``{filters.dateRange.to}``, and
    ``{filters(<column> AS timestamp)}`` bound the rows. Other forms, such as ``{filters.interval}``,
    only substitute a value, so a query that uses only them still reads all time.
    """

    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_placeholder(self, node: ast.Placeholder) -> None:
        chain = node.chain
        if chain == ["filters"] or (chain is not None and chain[:2] == ["filters", "dateRange"]):
            self.found = True
        elif isinstance(node.expr, ast.Call) and node.expr.name == "filters":
            self.found = self.found or any(
                isinstance(arg, ast.Alias)
                and arg.alias == "timestamp"
                and not (isinstance(arg.expr, ast.Constant) and arg.expr.value is None)
                for arg in node.expr.args
            )


def _has_date_bounding_placeholder(node: ast.Expr) -> bool:
    placeholders = _DateBoundingPlaceholders()
    placeholders.visit(node)
    return placeholders.found


def _graded_sql(
    name: str, output: dict | None, expected: dict | None
) -> tuple[dict[str, Any], ast.SelectQuery | ast.SelectSetQuery] | Score:
    """The saved SQL source and its parsed query, or the score to return when there is nothing to grade."""
    if not isinstance(expected, dict) or not isinstance(expected.get(name), dict):
        return Score(name=name, score=None, metadata={"reason": f"No {name} key on case"})
    source = _last_saved_sql(output)
    if source is None:
        return Score(name=name, score=None, metadata={"reason": "No SQL insight was saved"})
    node = _parse(source)
    if node is None:
        return Score(name=name, score=0.0, metadata={"reason": "The saved SQL does not parse"})
    return source, node


class SavedSqlInsight(Scorer):
    """Binary: did the agent save a SQL insight, on a dashboard when the case asks for one?

    ``expected = {"saved_sql_insight": {}}`` or ``{"saved_sql_insight": {"on_dashboard": True}}``

    This is the manipulation check for the suite: the other scorers grade the saved SQL, so a
    case without one tells nothing about date filters or ordering. ``on_dashboard`` passes when
    the call that saved the graded SQL insight sets a non-empty ``dashboards`` list, or a later
    ``insight-update`` of that same insight does. ``None`` if the spec is absent.
    """

    def _name(self) -> str:
        return "saved_sql_insight"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = expected.get(self._name()) if isinstance(expected, dict) else None
        if not isinstance(spec, dict):
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} key on case"})
        parser = parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})
        calls = [call for call in parser.get_tool_calls() if not call.is_error and call.name in _SAVE_TOOLS]
        saved = _saved_sql_calls(calls)
        if not saved:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No SQL insight was saved"})
        if spec.get("on_dashboard"):
            save_call = saved[-1][0]
            ids = _insight_ids(save_call)
            on_dashboard = bool(save_call.input.get("dashboards")) or any(
                call.name == "insight-update"
                and call.position > save_call.position
                and call.input.get("dashboards")
                and _insight_ids(call) & ids
                for call in calls
            )
            if not on_dashboard:
                return Score(
                    name=self._name(),
                    score=0.0,
                    metadata={"reason": "The SQL insight was not added to a dashboard", "insight_ids": sorted(ids)},
                )
        return Score(name=self._name(), score=1.0)


class SqlFollowsDateFilter(Scorer):
    """Binary: does the saved SQL insight follow the dashboard and insight date range?

    ``expected = {"sql_follows_date_filter": {}}``

    Passes when all of these are true:

    - The query has a date-bounding ``{filters}`` placeholder: ``{filters}``,
      ``{filters(<column> AS timestamp)}``, or ``{filters.dateRange.from}``.
    - The query has no hard-coded window, such as ``timestamp >= now() - INTERVAL 14 DAY``.
      A hard-coded window still clips the rows when a dashboard sets a wider range.
    - ``source.filters.dateRange.date_from`` is set. Without it, ``{filters}`` is ``TRUE`` and
      the insight shows all time instead of the window the user asked for.

    ``None`` when no SQL insight was saved (graded by ``saved_sql_insight``) or the spec is absent.
    """

    def _name(self) -> str:
        return "sql_follows_date_filter"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        graded = _graded_sql(self._name(), output, expected)
        if isinstance(graded, Score):
            return graded
        source, node = graded

        windows = _HardCodedWindows()
        windows.visit(node)
        filters = source.get("filters")
        date_range = filters.get("dateRange") if isinstance(filters, dict) else None
        failures = []
        if not _has_date_bounding_placeholder(node):
            failures.append("no {filters} placeholder")
        if windows.found:
            failures.append("hard-coded date window")
        if not (isinstance(date_range, dict) and date_range.get("date_from")):
            failures.append("no default filters.dateRange.date_from")
        return Score(
            name=self._name(),
            score=0.0 if failures else 1.0,
            metadata={"failures": failures, "hard_coded_windows": windows.found, "date_range": date_range},
        )


def _is_time_bucket(node: ast.Expr) -> bool:
    found = _calls_in(node)
    return (
        any(
            name.startswith("tostartof") or name in _TIME_BUCKET_FUNCTIONS or name in _CLOCK_FUNCTIONS
            for name in found.names
        )
        or "timestamp" in found.fields
    )


def _field_name(node: ast.Expr) -> str | None:
    return str(node.chain[-1]).lower() if isinstance(node, ast.Field) and node.chain else None


def _column_name(column: ast.Expr) -> str | None:
    return column.alias.lower() if isinstance(column, ast.Alias) else _field_name(column)


def _source_queries(
    select: ast.SelectQuery, ctes: dict[str, ast.Expr]
) -> list[tuple[ast.SelectQuery | ast.SelectSetQuery, dict[str, ast.Expr]]]:
    """The subqueries and CTE bodies that ``select`` reads from, each with the CTE scope to resolve it in.

    A CTE body is resolved without its own name, so ``WITH events AS (SELECT ... FROM events)``
    reads the physical ``events`` table and does not refer back to itself.
    """
    sources: list[tuple[ast.SelectQuery | ast.SelectSetQuery, dict[str, ast.Expr]]] = []
    join = select.select_from
    while join is not None:
        table: ast.Expr | None = join.table
        scope = ctes
        if isinstance(table, ast.Field) and len(table.chain) == 1:
            name = str(table.chain[0]).lower()
            table = ctes.get(name)
            scope = {key: value for key, value in ctes.items() if key != name}
        if isinstance(table, ast.SelectQuery | ast.SelectSetQuery):
            sources.append((table, scope))
        join = join.next_join
    return sources


def _time_columns(node: ast.SelectQuery | ast.SelectSetQuery, ctes: dict[str, ast.Expr]) -> set[str]:
    """Output columns that hold a time bucket, followed through subqueries, joins, and CTEs.

    Agents often fill empty buckets with a generated date series, such as
    ``SELECT today() - number AS day FROM numbers(14)``, joined to the counts, and select the
    bucket in the outer query only as ``d.day``.
    """
    select = _outer_select(node)
    ctes = {**ctes, **{name.lower(): cte.expr for name, cte in (select.ctes or {}).items()}}
    inner = set().union(*(_time_columns(source, scope) for source, scope in _source_queries(select, ctes)))
    names = set()
    for column in select.select or []:
        expr = column.expr if isinstance(column, ast.Alias) else column
        name = _column_name(column)
        if name and (_is_time_bucket(expr) or _field_name(expr) in inner):
            names.add(name)
    return names


def _is_aggregate(node: ast.Expr) -> bool:
    return any(find_hogql_aggregation(name) for name in _calls_in(node).raw_names)


def _order_key_kinds(node: ast.SelectQuery | ast.SelectSetQuery) -> list[tuple[ast.OrderExpr, str]]:
    """Each outer ``ORDER BY`` key, classed as ``time``, ``value`` (an aggregate), or ``group``."""
    select = _outer_select(node)
    columns = list(select.select or [])
    by_name = {name: column for column in columns if (name := _column_name(column))}
    time_columns = _time_columns(node, {})
    kinds = []
    for order in select.order_by or []:
        expr = order.expr
        if isinstance(expr, ast.Constant) and isinstance(expr.value, int) and 0 < expr.value <= len(columns):
            column: ast.Expr = columns[expr.value - 1]
        else:
            column = by_name.get(_field_name(expr) or "", expr)
        if _column_name(column) in time_columns or _field_name(expr) in time_columns or _is_time_bucket(column):
            kinds.append((order, "time"))
        elif _is_aggregate(column):
            kinds.append((order, "value"))
        else:
            kinds.append((order, "group"))
    return kinds


class SqlTimeAxisAscending(Scorer):
    """Binary: does the saved SQL time series sort its time column from oldest to newest?

    ``expected = {"sql_time_axis_ascending": {}}``

    A SQL chart takes its X axis from the row order. The outer query must order by its time
    bucket (by alias, position, or expression), and every time key must be ascending. A time
    bucket selected from a subquery, a join, or a CTE counts as the time bucket. A breakdown
    column can come before the time key, but an aggregate cannot, because ``ORDER BY uploads DESC, day``
    sorts the rows by value first. A missing ``ORDER BY`` fails, because ClickHouse returns
    grouped rows in no fixed order. ``None`` when no SQL insight was saved or the spec is absent.
    """

    def _name(self) -> str:
        return "sql_time_axis_ascending"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        graded = _graded_sql(self._name(), output, expected)
        if isinstance(graded, Score):
            return graded
        _, node = graded

        kinds = _order_key_kinds(node)
        time_positions = [index for index, (_, kind) in enumerate(kinds) if kind == "time"]
        if not time_positions:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No ORDER BY on the time column"})
        descending = [_hogql_text(order.expr) for order, kind in kinds if kind == "time" and order.order == "DESC"]
        values_first = [_hogql_text(order.expr) for order, kind in kinds[: time_positions[0]] if kind == "value"]
        return Score(
            name=self._name(),
            score=0.0 if descending or values_first else 1.0,
            metadata={
                "order_keys": [f"{_hogql_text(order)} ({kind})" for order, kind in kinds],
                "descending": descending,
                "values_before_time": values_first,
            },
        )
