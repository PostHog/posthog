from collections.abc import Mapping
from dataclasses import field
from datetime import datetime
from typing import Any, cast

from pydantic import ValidationError

from posthog.schema import ActionsNode, EventsNode, GroupNode, HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.events import EVENTS_TABLE_TYPES
from posthog.hogql.database.schema.util.where_clause_extractor import contains_subquery, top_level_conjuncts
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.dataclasses import frozen
from posthog.hogql_queries.query_runner import get_query_runner_or_none
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team import Team
from posthog.models.user import User

from products.product_analytics.backend.hogql_queries.funnels.funnels_query_runner import FunnelsQueryRunner
from products.product_analytics.backend.hogql_queries.lifecycle.lifecycle_query_runner import LifecycleQueryRunner
from products.product_analytics.backend.hogql_queries.stickiness.stickiness_query_runner import StickinessQueryRunner
from products.product_analytics.backend.hogql_queries.trends.trends_query_runner import TrendsQueryRunner

# Exact classes only: a subclass, such as the slope graph runner, can run a query of its own in `_calculate()`.
_CHART_RUNNERS = (TrendsQueryRunner, FunnelsQueryRunner, StickinessQueryRunner, LifecycleQueryRunner)
# Event names and dates are in the sort key of the events table, so a filter on them reads no property of any event.
_SORT_KEY_FIELDS = ("event", "timestamp")
_ORDER_KEEPING = ("toDate", "toDateTime", "toTimeZone", "assumeNotNull")
# The side of a comparison that is the later value, so a timestamp there is bounded from below.
_LOWER_BOUND_SIDE = {
    ast.CompareOperationOp.Gt: "left",
    ast.CompareOperationOp.GtEq: "left",
    ast.CompareOperationOp.Lt: "right",
    ast.CompareOperationOp.LtEq: "right",
}


@frozen
class ChartEvents:
    """The events the chart's own query reads, as one filter on the events table."""

    # The alias the chart gives the events table. The filters refer to it.
    alias: str | None
    where: ast.Expr
    # The part of `where` on event names and dates only, so a count with it reads no event property.
    sort_key_where: ast.Expr
    # The first and last moment any of the chart's queries reads, in the project's timezone.
    date_from: datetime
    date_to: datetime
    filters_test_accounts: bool
    modifiers: HogQLQueryModifiers
    # The database the filter was read with, for the queries that run it.
    database: Database = field(repr=False, compare=False)

    def select(
        self,
        query: str,
        *,
        where: ast.Expr,
        sample: ast.SampleExpr | None = None,
        **placeholders: ast.Expr,
    ) -> ast.SelectQuery:
        """`query`, a select from the events table, set to read these events with `where`."""
        select = cast(ast.SelectQuery, parse_select(query, placeholders=placeholders))
        select.select_from = ast.JoinExpr(table=ast.Field(chain=["events"]), alias=self.alias, sample=sample)
        select.where = where
        return select

    def timestamp(self) -> ast.Field:
        return ast.Field(chain=[self.alias, "timestamp"] if self.alias else ["timestamp"])


def chart_events(query: Mapping[str, Any], team: Team, user: User) -> ChartEvents | None:
    """The events an insight's chart reads, taken from the query the chart runs.

    None for an insight the checks do not support. A chart with several series reads the events of any of them.
    """
    try:
        runner = get_query_runner_or_none(dict(query), team, user=user)
    except ValidationError:
        return None
    if not isinstance(runner, _CHART_RUNNERS) or type(runner) not in _CHART_RUNNERS:
        return None
    # A data warehouse series reads no events.
    if not runner.query.series or not all(_reads_events(series) for series in runner.query.series):
        return None
    runner.validate()
    database = runner.shared_database
    filters: list[tuple[str | None, ast.Expr, QueryDateRange]] = []
    for chart_query, date_range in _chart_queries(runner):
        for read in _events_reads(chart_query, database):
            read_filter = _read_filter(read)
            if read_filter is None:
                return None
            filters.append((*read_filter, date_range))
    aliases = {alias for alias, _, _ in filters}
    if len(aliases) != 1:
        return None
    alias = aliases.pop()
    wheres = [_from_date(where, date_range, alias) for _, where, date_range in filters]
    date_ranges = [date_range for _, _, date_range in filters]
    return ChartEvents(
        alias=alias,
        where=_any_of(wheres),
        sort_key_where=_any_of([_sort_key_part(where, alias) or ast.Constant(value=True) for where in wheres]),
        date_from=min(date_range.date_from() for date_range in date_ranges),
        date_to=max(date_range.date_to() for date_range in date_ranges),
        filters_test_accounts=bool(runner.query.filterTestAccounts),
        modifiers=runner.modifiers,
        database=database,
    )


def _reads_events(series: object) -> bool:
    if isinstance(series, GroupNode):
        return all(isinstance(node, EventsNode | ActionsNode) for node in series.nodes)
    return isinstance(series, EventsNode | ActionsNode)


def _chart_queries(
    runner: TrendsQueryRunner | FunnelsQueryRunner | StickinessQueryRunner | LifecycleQueryRunner,
) -> list[tuple[ast.Expr, QueryDateRange]]:
    """Each query the chart runs, with the date range it reads."""
    if isinstance(runner, TrendsQueryRunner | StickinessQueryRunner):
        previous = [series.is_previous_period_series for series in runner.series]
        return [
            (query, runner.query_previous_date_range if is_previous else runner.query_date_range)
            for is_previous, query in zip(previous, runner.to_queries(), strict=True)
        ]
    if isinstance(runner, FunnelsQueryRunner):
        queries: list[tuple[ast.Expr, QueryDateRange]] = [(runner.to_query(), runner.query_date_range)]
        # The chart runs the previous period as a funnel of its own.
        if runner._is_compare_active():
            queries.append((runner._build_previous_funnel().get_query(), runner.query_previous_date_range))
        return queries
    return [(runner.to_query(), runner.query_date_range)]


def _events_reads(
    query: ast.Expr | None, database: Database, ctes: Mapping[str, ast.CTE] | None = None
) -> list[ast.SelectQuery]:
    """The selects that read the events table, found through each FROM, so a subquery in a filter is not one."""
    if isinstance(query, ast.SelectSetQuery):
        return [read for select in query.select_queries() for read in _events_reads(select, database, ctes)]
    if not isinstance(query, ast.SelectQuery) or query.select_from is None:
        return []
    ctes = {**(ctes or {}), **(query.ctes or {})}
    table = query.select_from.table
    if isinstance(table, ast.Field) and len(table.chain) == 1 and table.chain[0] in ctes:
        cte = ctes[str(table.chain[0])]
        return _events_reads(cte.expr, database, ctes) if cte.cte_type == "subquery" else []
    if isinstance(table, ast.Field):
        name = [str(part) for part in table.chain]
        is_events = database.has_table(name) and isinstance(database.get_table(name), EVENTS_TABLE_TYPES)
        return [query] if is_events else []
    return _events_reads(table, database, ctes)


def _read_filter(read: ast.SelectQuery) -> tuple[str | None, ast.Expr] | None:
    """The read's table alias and filter, with each column alias of its select replaced by the expression it names.

    None for a read the checks cannot filter the same way.
    """
    table = cast(ast.JoinExpr, read.select_from)
    join_filter = _join_filter(table.next_join) if table.next_join else None
    if table.next_join and join_filter is None:
        return None
    where = _all_of([expr for expr in (read.prewhere, read.where, join_filter) if expr is not None])
    aliases = {expr.alias: expr.expr for expr in read.select if isinstance(expr, ast.Alias)}
    return table.alias, _AliasInliner(aliases).visit(where)


def _join_filter(join: ast.JoinExpr) -> ast.Expr | None:
    """An inner join on one column keeps an event when the joined table has its value, so it reads as `IN`.

    None for any other join, which the checks do not read.
    """
    constraint = join.constraint.expr if join.constraint else None
    if (
        join.next_join is not None
        or join.join_type != "INNER JOIN"
        or not isinstance(constraint, ast.CompareOperation)
        or constraint.op != ast.CompareOperationOp.Eq
    ):
        return None
    left_on, right_on = _is_on(constraint.left, join.alias), _is_on(constraint.right, join.alias)
    if left_on == right_on:
        return None
    event_side, joined_side = (constraint.right, constraint.left) if left_on else (constraint.left, constraint.right)
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=event_side,
        right=ast.SelectQuery(select=[joined_side], select_from=ast.JoinExpr(table=join.table, alias=join.alias)),
    )


def _is_on(expr: ast.Expr, alias: str | None) -> bool:
    return isinstance(expr, ast.Field) and alias is not None and expr.chain[0] == alias


class _AliasInliner(CloningVisitor):
    def __init__(self, aliases: dict[str, ast.Expr]):
        super().__init__(clear_types=True, clear_locations=True)
        self.aliases = aliases

    def visit_field(self, node: ast.Field) -> ast.Expr:
        name = node.chain[0]
        if len(node.chain) != 1 or not isinstance(name, str) or name not in self.aliases:
            return super().visit_field(node)
        return _AliasInliner({key: expr for key, expr in self.aliases.items() if key != name}).visit(self.aliases[name])

    def visit_select_query(self, node: ast.SelectQuery) -> ast.Expr:
        return clone_expr(node, clear_types=True, clear_locations=True)

    def visit_lambda(self, node: ast.Lambda) -> ast.Expr:
        # Inside a lambda, an argument hides the select alias of the same name.
        inliner = _AliasInliner({key: expr for key, expr in self.aliases.items() if key not in node.args})
        return CloningVisitor.visit_lambda(inliner, node)


def _from_date(where: ast.Expr, date_range: QueryDateRange, alias: str | None) -> ast.Expr:
    """`where`, with the start the chart gives its date range when it reads events from any date before that.

    A "first time for user" series reads every earlier event to find the first one. The checks read its range only.
    """
    for part in top_level_conjuncts(where):
        if (
            isinstance(part, ast.CompareOperation)
            and part.op in _LOWER_BOUND_SIDE
            and _is_timestamp(getattr(part, _LOWER_BOUND_SIDE[part.op]), alias)
        ):
            return where
    start = ast.CompareOperation(
        op=ast.CompareOperationOp.GtEq,
        left=ast.Field(chain=[alias, "timestamp"] if alias else ["timestamp"]),
        right=date_range.to_placeholders()["date_from_with_adjusted_start_of_interval"],
    )
    return ast.And(exprs=[where, start])


def _is_timestamp(expr: ast.Expr, alias: str | None) -> bool:
    """Whether `expr` is the timestamp, or a value that keeps the order of timestamps, such as its start of day."""
    if isinstance(expr, ast.Call) and expr.args and (expr.name.startswith("toStartOf") or expr.name in _ORDER_KEEPING):
        return _is_timestamp(expr.args[0], alias)
    return isinstance(expr, ast.Field) and _is_events_column(expr, alias, ("timestamp",))


def _is_events_column(field: ast.Field, alias: str | None, names: tuple[str, ...]) -> bool:
    return field.chain[-1] in names and field.chain[:-1] in ([], [alias or "events"])


class _OtherFieldFinder(TraversingVisitor):
    def __init__(self, alias: str | None):
        super().__init__()
        self.alias = alias
        self.found = False

    def visit_field(self, node: ast.Field) -> None:
        self.found = self.found or not _is_events_column(node, self.alias, _SORT_KEY_FIELDS)


def _reads_sort_key_only(expr: ast.Expr, alias: str | None) -> bool:
    finder = _OtherFieldFinder(alias)
    finder.visit(expr)
    return not finder.found and not contains_subquery(expr)


def _sort_key_part(expr: ast.Expr, alias: str | None) -> ast.Expr | None:
    """A filter on event names and dates only that keeps every event `expr` keeps, or None when there is none."""
    if isinstance(expr, ast.And):
        parts = [part for part in (_sort_key_part(child, alias) for child in expr.exprs) if part is not None]
        return _all_of(parts) if parts else None
    if isinstance(expr, ast.Or):
        branches = [_sort_key_part(child, alias) for child in expr.exprs]
        return None if any(branch is None for branch in branches) else _any_of(cast(list[ast.Expr], branches))
    return expr if _reads_sort_key_only(expr, alias) else None


def _all_of(conditions: list[ast.Expr]) -> ast.Expr:
    if not conditions:
        return ast.Constant(value=True)
    return conditions[0] if len(conditions) == 1 else ast.And(exprs=conditions)


def _any_of(conditions: list[ast.Expr]) -> ast.Expr:
    return conditions[0] if len(conditions) == 1 else ast.Or(exprs=conditions)
