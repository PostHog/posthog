from collections.abc import Mapping
from typing import Any, cast

from pydantic import ValidationError

from posthog.schema import EventsNode, FunnelsQuery, HogQLQueryModifiers, LifecycleQuery, StickinessQuery, TrendsQuery

from posthog.hogql import ast
from posthog.hogql.database.schema.util.where_clause_extractor import top_level_conjuncts
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.dataclasses import frozen
from posthog.hogql_queries.apply_dashboard_filters import WRAPPER_NODE_KINDS
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team import Team
from posthog.models.user import User

_WRAPPER_KINDS = {kind.value for kind in WRAPPER_NODE_KINDS}
_SERIES_QUERIES: dict[str, type[TrendsQuery | FunnelsQuery | StickinessQuery | LifecycleQuery]] = {
    "TrendsQuery": TrendsQuery,
    "FunnelsQuery": FunnelsQuery,
    "StickinessQuery": StickinessQuery,
    "LifecycleQuery": LifecycleQuery,
}
# Event names and dates are in the sort key of the events table, so a filter on them reads no property of any event.
_SORT_KEY_FIELDS = ("event", "timestamp")
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
    modifiers: HogQLQueryModifiers

    def select(
        self, query: str, *, where: ast.Expr, sample: ast.SampleExpr | None = None, **placeholders: ast.Expr
    ) -> ast.SelectQuery:
        """`query`, a select from the events table, set to read these events with `where`."""
        select = cast(ast.SelectQuery, parse_select(query, placeholders=placeholders))
        select.select_from = ast.JoinExpr(table=ast.Field(chain=["events"]), alias=self.alias, sample=sample)
        select.where = where
        return select


def chart_events(query: Mapping[str, Any], team: Team, user: User) -> ChartEvents | None:
    """The events an insight's chart reads, taken from the query the chart runs.

    None for an insight the checks do not support. A chart with several series reads the events of any of them.
    """
    source = _supported_source(query)
    if source is None:
        return None
    runner = get_query_runner(source, team, modifiers=source.modifiers, user=user)
    runner.validate()
    to_queries = getattr(runner, "to_queries", None)
    chart_queries = to_queries() if to_queries else [runner.to_query()]
    reads = [read for chart_query in chart_queries for read in _events_reads(chart_query)]
    aliases = {cast(ast.JoinExpr, read.select_from).alias for read in reads}
    filters = [_read_filter(read) for read in reads]
    wheres = [where for where in filters if where is not None]
    if len(aliases) != 1 or len(wheres) < len(filters):
        return None
    alias = aliases.pop()
    # A "first time for user" series reads every earlier event to find the first one. The checks read the chart's range.
    date_range: QueryDateRange | None = getattr(runner, "query_date_range", None)
    if date_range is not None:
        wheres = [_from_date(where, date_range, alias) for where in wheres]
    return ChartEvents(
        alias=alias,
        where=_any_of(wheres),
        sort_key_where=_any_of(
            [
                _all_of([part for part in top_level_conjuncts(where) if _sort_key_fields(part, alias) is not None])
                for where in wheres
            ]
        ),
        modifiers=runner.modifiers,
    )


def _supported_source(query: Mapping[str, Any]) -> TrendsQuery | FunnelsQuery | StickinessQuery | LifecycleQuery | None:
    node: Any = query
    while isinstance(node, Mapping) and node.get("kind") in _WRAPPER_KINDS:
        node = node.get("source")
    if not isinstance(node, Mapping):
        return None
    model = _SERIES_QUERIES.get(str(node.get("kind")))
    if model is None:
        return None
    try:
        source = model.model_validate(node)
    except ValidationError:
        return None
    # An action or a data warehouse series has no event name to check.
    if not source.series or not all(isinstance(series, EventsNode) for series in source.series):
        return None
    return source


def _events_reads(query: ast.Expr | None) -> list[ast.SelectQuery]:
    """The selects that read the events table, found through each FROM, so a subquery in a filter is not one."""
    if isinstance(query, ast.SelectSetQuery):
        return [read for select in query.select_queries() for read in _events_reads(select)]
    if not isinstance(query, ast.SelectQuery) or query.select_from is None:
        return []
    table = query.select_from.table
    if isinstance(table, ast.Field) and table.chain == ["events"]:
        return [query]
    return _events_reads(table)


def _read_filter(read: ast.SelectQuery) -> ast.Expr | None:
    """The read's filter, with each column alias of its select replaced by the expression it names."""
    join = cast(ast.JoinExpr, read.select_from).next_join
    join_filter = _join_filter(join) if join else None
    if join and join_filter is None:
        return None
    where = _all_of([expr for expr in (read.prewhere, read.where, join_filter) if expr is not None])
    return _AliasInliner({expr.alias: expr.expr for expr in read.select if isinstance(expr, ast.Alias)}).visit(where)


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
    event_side, joined_side = sorted((constraint.left, constraint.right), key=lambda side: _is_on(side, join.alias))
    if not _is_on(joined_side, join.alias) or _is_on(event_side, join.alias):
        return None
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


def _from_date(where: ast.Expr, date_range: QueryDateRange, alias: str | None) -> ast.Expr:
    """`where`, with the start of the chart's date range when it reads events from any date before that."""
    for part in top_level_conjuncts(where):
        if isinstance(part, ast.CompareOperation) and part.op in _LOWER_BOUND_SIDE:
            side = part.left if _LOWER_BOUND_SIDE[part.op] == "left" else part.right
            if "timestamp" in (_sort_key_fields(side, alias) or ()):
                return where
    start = ast.CompareOperation(
        op=ast.CompareOperationOp.GtEq,
        left=ast.Field(chain=[alias, "timestamp"] if alias else ["timestamp"]),
        right=date_range.date_from_as_hogql(),
    )
    return ast.And(exprs=[where, start])


class _SortKeyReader(TraversingVisitor):
    def __init__(self, alias: str | None):
        super().__init__()
        self.table = [alias or "events"]
        self.fields: set[str | int] = set()
        self.reads_other_fields = False

    def visit_field(self, node: ast.Field) -> None:
        self.fields.add(node.chain[-1])
        if node.chain[-1] not in _SORT_KEY_FIELDS or node.chain[:-1] not in ([], self.table):
            self.reads_other_fields = True

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.reads_other_fields = True


def _sort_key_fields(expr: ast.Expr, alias: str | None) -> set[str | int] | None:
    """The event name and date fields `expr` reads, or None when it reads any other field."""
    reader = _SortKeyReader(alias)
    reader.visit(expr)
    return None if reader.reads_other_fields else reader.fields


def _all_of(conditions: list[ast.Expr]) -> ast.Expr:
    if not conditions:
        return ast.Constant(value=True)
    return conditions[0] if len(conditions) == 1 else ast.And(exprs=conditions)


def _any_of(conditions: list[ast.Expr]) -> ast.Expr:
    return conditions[0] if len(conditions) == 1 else ast.Or(exprs=conditions)
