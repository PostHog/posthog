import functools
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from posthog.schema import ExecutionTarget, HogQLQuery, HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import DatabaseField, ExpressionField
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.person_distinct_id_overrides import RawPersonDistinctIdOverridesTable
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.functions.mapping import find_hogql_posthog_function
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import replace_placeholders
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.transforms.preaggregated_table_transformation import is_integer_timezone
from posthog.hogql.visitor import TraversingVisitor, clear_locations, clone_expr

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.series_values_preaggregated_sql import (
    DISTRIBUTED_SERIES_VALUES_PREAGGREGATED_TABLE,
)
from posthog.clickhouse.query_tagging import tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.access_control.backend.facade.api import team_has_property_access_rules
from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationTable,
    ensure_precomputed,
)
from products.data_modeling.backend.facade.api import IncrementalConfig, check_incremental_eligibility
from products.product_analytics.backend.facade.contracts import ClosedSqlSeriesValues, SeriesValuesUnavailable
from products.product_analytics.backend.hogql_queries.trends.series_values_precompute import (
    MAX_RANGE_DAYS,
    READ_SETTINGS,
    crosses_dst,
    insert_time_cap,
    ttl_schedule,
)

ENGINE_VERSION = "sql_series_values_v1"
SOURCE_ALIAS = "user_query"

_TIMESTAMP = "timestamp"
_COMPILED_NODES = frozenset(
    {
        ast.SelectQuery,
        ast.JoinExpr,
        ast.JoinConstraint,
        ast.Alias,
        ast.Field,
        ast.Constant,
        ast.Call,
        ast.CompareOperation,
        ast.And,
        ast.Or,
        ast.Not,
        ast.ArithmeticOperation,
        ast.Array,
        ast.Tuple,
        ast.Lambda,
        ast.PropertyAccess,
        ast.JsonSubcolumnAccess,
        ast.ArrayAccess,
        ast.TupleAccess,
        ast.OrderExpr,
    }
)
_COMPILED_FIELD_TYPES = (ast.FieldType, ast.FieldAliasType, ast.LambdaArgumentType, ast.AsteriskType)
_EVENT_COLUMNS = {
    "person_id",
    *(
        name
        for name, field in EventsTable().fields.items()
        if isinstance(field, DatabaseField) and not isinstance(field, ExpressionField)
    ),
}
_EVENT_SUBTABLE_FIELDS = {
    "poe": {"id", "created_at", "properties"},
    **{f"goe_{index}": {"key", "created_at", "properties"} for index in range(5)},
}
_ANCHORS = {"now", "today"}
_INTERVAL_UNITS: dict[str, Callable[[int], relativedelta]] = {
    "Second": lambda count: relativedelta(seconds=count),
    "Minute": lambda count: relativedelta(minutes=count),
    "Hour": lambda count: relativedelta(hours=count),
    "Day": lambda count: relativedelta(days=count),
    "Week": lambda count: relativedelta(weeks=count),
    "Month": lambda count: relativedelta(months=count),
    "Quarter": lambda count: relativedelta(months=3 * count),
    "Year": lambda count: relativedelta(years=count),
}
_LOWER_BOUND_OPS = {ast.CompareOperationOp.GtEq, ast.CompareOperationOp.Gt}
_UPPER_BOUND_OPS = {ast.CompareOperationOp.Lt, ast.CompareOperationOp.LtEq}


@frozen
class _Window:
    anchor: str
    lookback: relativedelta
    timestamp: ast.Field


@frozen
class _Where:
    window: _Window
    other_conjuncts: tuple[ast.Expr, ...]


@frozen
class _SqlShape:
    select: ast.SelectQuery
    bucket_alias: str
    hourly: bool
    utc_bucket: bool
    where: _Where


@frozen
class _Bucket:
    alias: ast.Alias
    hourly: bool
    utc: bool


class _ResolvedAwayFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        if node.op in (ast.CompareOperationOp.InCohort, ast.CompareOperationOp.NotInCohort):
            self.found = True
        super().visit_compare_operation(node)

    def visit_call(self, node: ast.Call) -> None:
        if node.name.lower() == "cohort" or find_hogql_posthog_function(node.name) is not None:
            self.found = True
        super().visit_call(node)

    def visit_hogqlx_tag(self, node: ast.HogQLXTag) -> None:
        self.found = True


class _OtherSourceFinder(_ResolvedAwayFinder):
    def __init__(self, root: ast.SelectQuery) -> None:
        super().__init__()
        self.root = root
        self.qualifiers = _qualifiers(root)
        self.aliases = {item.alias for item in root.select if isinstance(item, ast.Alias)}
        self.lambda_args: list[str] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if node is not self.root:
            self.found = True
            return
        super().visit_select_query(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        self.found = True

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        pass

    def visit_lambda(self, node: ast.Lambda) -> None:
        self.lambda_args.extend(node.args)
        super().visit_lambda(node)
        del self.lambda_args[len(self.lambda_args) - len(node.args) :]

    def visit_call(self, node: ast.Call) -> None:
        star = len(node.args) == 1 and isinstance(node.args[0], ast.Field) and node.args[0].chain == ["*"]
        super().visit_call(replace(node, args=[]) if star and node.name.lower() == "count" else node)

    def visit_field(self, node: ast.Field) -> None:
        chain = node.chain[1:] if len(node.chain) > 1 and node.chain[0] in self.qualifiers else node.chain
        if not chain or not self._is_event_column(chain):
            self.found = True

    def _is_event_column(self, chain: list[str | int]) -> bool:
        head = str(chain[0])
        if len(chain) > 1:
            return head == "properties" or str(chain[1]) in _EVENT_SUBTABLE_FIELDS.get(head, ())
        return head in _EVENT_COLUMNS or head in self.lambda_args or head in self.aliases


class _ReadRefused(Exception):
    pass


class _CompiledReadChecker(TraversingVisitor):
    def __init__(self, root: ast.SelectQuery, person_join: Callable[[], ast.JoinExpr | None]) -> None:
        super().__init__()
        self.sources = {id(root)}
        self.person_join = person_join

    def visit(self, node: ast.AST | None) -> None:
        if node is None or isinstance(node, ast.Type):
            return
        if type(node) not in _COMPILED_NODES:
            raise _ReadRefused
        if isinstance(node, ast.SelectQuery) and id(node) not in self.sources:
            raise _ReadRefused
        super().visit(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if node.ctes or node.array_join_list or node.window_exprs:
            raise _ReadRefused
        super().visit_select_query(node)

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if node.table_args is not None or node.sample is not None or node.column_aliases or node.table_final:
            raise _ReadRefused
        if node.join_type is not None:
            if not self._is_person_join(node):
                raise _ReadRefused
        elif isinstance(node.table, ast.SelectQuery) and isinstance(
            node.type, (ast.SelectQueryType, ast.SelectQueryAliasType)
        ):
            self.sources.add(id(node.table))
            self.visit(node.table)
        elif not (isinstance(node.table, ast.Field) and isinstance(_read_table(node.type), EventsTable)):
            raise _ReadRefused
        self.visit(node.constraint)
        self.visit(node.next_join)

    def visit_field(self, node: ast.Field) -> None:
        if not isinstance(node.type, _COMPILED_FIELD_TYPES):
            raise _ReadRefused

    def visit_call(self, node: ast.Call) -> None:
        if find_hogql_posthog_function(node.name) is not None:
            raise _ReadRefused
        super().visit_call(node)

    def _is_person_join(self, node: ast.JoinExpr) -> bool:
        if not isinstance(node.table, ast.SelectQuery):
            return False
        reference = self.person_join()
        return reference is not None and _join_key(node) == _join_key(reference)


class _PlaceholderFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.chains: list[list[str | int] | None] = []

    def visit_placeholder(self, node: ast.Placeholder) -> None:
        self.chains.append(node.chain)


def _query_refusal(query: HogQLQuery) -> str | None:
    if query.connectionId or query.sendRawQuery or query.executionTarget not in (None, ExecutionTarget.DEFAULT):
        return "connection"
    if query.variables or query.values:
        return "variables"
    if query.modifiers is not None and query.modifiers.model_dump(exclude_none=True):
        return "modifiers"
    return None


def _placeholder_refusal(node: ast.Expr) -> str | None:
    finder = _PlaceholderFinder()
    finder.visit(node)
    if not finder.chains:
        return None
    return "filters_placeholder" if any(chain == ["filters"] for chain in finder.chains) else "variables"


def _source_refusal(select: ast.SelectQuery) -> str | None:
    source = select.select_from
    if select.ctes or source is None or source.next_join is not None or source.sample is not None:
        return "source"
    if select.array_join_op is not None or select.prewhere is not None:
        return "source"
    if source.table_args is not None or source.column_aliases is not None:
        return "source"
    if not isinstance(source.table, ast.Field) or source.table.chain != ["events"]:
        return "source"
    finder = _OtherSourceFinder(select)
    finder.visit(select)
    return "source" if finder.found else None


def _read_table(table_type: ast.Type | None) -> object:
    while isinstance(table_type, ast.TableAliasType):
        table_type = table_type.table_type
    return table_type.table if isinstance(table_type, ast.TableType) else None


def _join_key(node: ast.JoinExpr) -> ast.JoinExpr:
    return clone_expr(replace(node, next_join=None), clear_types=True, clear_locations=True)


def _compiled(
    select: ast.SelectQuery, team: Team, database: Database, modifiers: HogQLQueryModifiers
) -> ast.SelectQuery:
    context = HogQLContext(
        team_id=team.pk,
        team=team,
        enable_select_queries=True,
        limit_top_select=False,
        modifiers=modifiers.model_copy(),
        bypass_warehouse_access_control=True,
        database=database,
    )
    _, prepared = prepare_and_print_ast(clone_expr(select), context=context, dialect="clickhouse")
    if not isinstance(prepared, ast.SelectQuery):
        raise _ReadRefused
    return prepared


def _person_join(
    source_alias: str | None, team: Team, database: Database, modifiers: HogQLQueryModifiers
) -> ast.JoinExpr | None:
    probe = ast.SelectQuery(
        select=[ast.Field(chain=["person_id"])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), alias=source_alias),
    )
    source = _compiled(probe, team, database, modifiers).select_from
    join = None if source is None else source.next_join
    if join is None or join.next_join is not None or not isinstance(join.table, ast.SelectQuery):
        return None
    inner = join.table.select_from
    if inner is None or inner.next_join is not None or not isinstance(inner.table, ast.Field):
        return None
    return join if isinstance(_read_table(inner.type), RawPersonDistinctIdOverridesTable) else None


def _compiled_read_refusal(
    insert_query: ast.SelectQuery,
    source_alias: str | None,
    team: Team,
    database: Database,
    modifiers: HogQLQueryModifiers,
    bounds: tuple[datetime, datetime],
) -> str | None:
    window_min, window_max = bounds
    bound = replace_placeholders(
        insert_query,
        {"time_window_min": ast.Constant(value=window_min), "time_window_max": ast.Constant(value=window_max)},
    )
    if not isinstance(bound, ast.SelectQuery):
        return "source"
    resolved_away = _ResolvedAwayFinder()
    resolved_away.visit(bound)
    if resolved_away.found:
        return "source"
    person_join = functools.cache(lambda: _person_join(source_alias, team, database, modifiers))
    try:
        compiled = _compiled(bound, team, database, modifiers)
        _CompiledReadChecker(compiled, person_join).visit(compiled)
    except (_ReadRefused, BaseHogQLError):
        return "source"
    return None


def _source_alias(select: ast.SelectQuery) -> str | None:
    return select.select_from.alias if select.select_from else None


def _qualifiers(select: ast.SelectQuery) -> set[str]:
    alias = _source_alias(select)
    return {"events", alias} if alias else {"events"}


def _output_name(item: ast.Expr) -> str | None:
    if isinstance(item, ast.Alias):
        return item.alias
    if isinstance(item, ast.Field) and len(item.chain) == 1:
        return str(item.chain[0])
    return None


def _is_timestamp(expr: ast.Expr, select: ast.SelectQuery) -> bool:
    if not isinstance(expr, ast.Field):
        return False
    chain = expr.chain
    return chain[-1] == _TIMESTAMP and (len(chain) == 1 or (len(chain) == 2 and chain[0] in _qualifiers(select)))


def _bucket(select: ast.SelectQuery) -> _Bucket | str:
    if select.group_by_mode is not None or not select.group_by or len(select.group_by) != 1:
        return "group_by"
    [key] = select.group_by
    aliases = [item for item in select.select if isinstance(item, ast.Alias)]
    if isinstance(key, ast.Field) and len(key.chain) == 1:
        bucket = next((item for item in aliases if item.alias == key.chain[0]), None)
    else:
        cleared = clear_locations(key)
        bucket = next((item for item in aliases if clear_locations(item.expr) == cleared), None)
    if bucket is None:
        return "group_by"
    expr = bucket.expr
    if not isinstance(expr, ast.Call) or not expr.args or not _is_timestamp(expr.args[0], select):
        return "bucket"
    if expr.name == "toStartOfHour" and len(expr.args) == 1:
        return _Bucket(alias=bucket, hourly=True, utc=False)
    if expr.name == "toDate" and len(expr.args) == 1:
        return _Bucket(alias=bucket, hourly=False, utc=False)
    if expr.name == "toStartOfDay":
        if len(expr.args) == 1:
            return _Bucket(alias=bucket, hourly=False, utc=False)
        if len(expr.args) == 2 and isinstance(expr.args[1], ast.Constant) and expr.args[1].value == "UTC":
            return _Bucket(alias=bucket, hourly=False, utc=True)
    return "bucket"


def _anchor(expr: ast.Expr) -> str | None:
    return expr.name if isinstance(expr, ast.Call) and expr.name in _ANCHORS and not expr.args else None


def _positive_int(expr: ast.Expr) -> int | None:
    if isinstance(expr, ast.Constant) and type(expr.value) is int and expr.value > 0:
        return expr.value
    return None


def _lookback(unit: str, amount: ast.Expr) -> relativedelta | None:
    count = _positive_int(amount)
    if unit not in _INTERVAL_UNITS or count is None:
        return None
    return _INTERVAL_UNITS[unit](count)


def _interval_lookback(expr: ast.Expr) -> relativedelta | None:
    if isinstance(expr, ast.Call) and expr.name.startswith("toInterval") and len(expr.args) == 1:
        return _lookback(expr.name.removeprefix("toInterval"), expr.args[0])
    return None


def _lower_bound(expr: ast.Expr) -> tuple[str, relativedelta] | None:
    anchor: ast.Expr | None = None
    lookback: relativedelta | None = None
    if isinstance(expr, ast.ArithmeticOperation) and expr.op == ast.ArithmeticOperationOp.Sub:
        anchor, lookback = expr.left, _interval_lookback(expr.right)
    elif isinstance(expr, ast.Call) and len(expr.args) == 2:
        if expr.name == "minus":
            anchor, lookback = expr.args[0], _interval_lookback(expr.args[1])
        elif expr.name.startswith("subtract") and expr.name.endswith("s"):
            anchor, lookback = expr.args[0], _lookback(expr.name.removeprefix("subtract")[:-1], expr.args[1])
    anchor_name = None if anchor is None else _anchor(anchor)
    if anchor_name is None or lookback is None:
        return None
    return anchor_name, lookback


def _where(select: ast.SelectQuery) -> _Where | str:
    where = select.where
    conjuncts = list(where.exprs) if isinstance(where, ast.And) else [where] if where is not None else []
    lower: list[tuple[ast.Field, tuple[str, relativedelta]]] = []
    upper: list[ast.Expr] = []
    other: list[ast.Expr] = []
    for conjunct in conjuncts:
        if isinstance(conjunct, ast.CompareOperation) and _is_timestamp(conjunct.left, select):
            assert isinstance(conjunct.left, ast.Field)
            bound = _lower_bound(conjunct.right) if conjunct.op in _LOWER_BOUND_OPS else None
            if bound is not None:
                lower.append((conjunct.left, bound))
                continue
            if conjunct.op in _UPPER_BOUND_OPS and _anchor(conjunct.right) == "now":
                upper.append(conjunct)
                continue
        other.append(conjunct)
    if len(lower) != 1 or len(upper) > 1:
        return "window"
    [(timestamp, (anchor, lookback))] = lower
    return _Where(window=_Window(anchor=anchor, lookback=lookback, timestamp=timestamp), other_conjuncts=tuple(other))


def _shape(sql: str) -> _SqlShape | str:
    try:
        node = parse_select(sql)
    except BaseHogQLError:
        return "parse_error"
    if not isinstance(node, ast.SelectQuery):
        return "set_operation"
    placeholder_refusal = _placeholder_refusal(node)
    if placeholder_refusal is not None:
        return placeholder_refusal
    source_refusal = _source_refusal(node)
    if source_refusal is not None:
        return source_refusal
    bucket = _bucket(node)
    if isinstance(bucket, str):
        return bucket
    if node.order_by and any(
        not isinstance(order.expr, ast.Field) or order.expr.chain != [bucket.alias.alias] for order in node.order_by
    ):
        return "order_by"
    if node.limit_by is not None or node.offset is not None or node.limit_with_ties:
        return "limit"
    if node.limit is not None and _positive_int(node.limit) is None:
        return "limit"
    where = _where(node)
    if isinstance(where, str):
        return where
    return _SqlShape(
        select=clone_expr(node, clear_locations=True),
        bucket_alias=bucket.alias.alias,
        hourly=bucket.hourly,
        utc_bucket=bucket.utc,
        where=_Where(
            window=where.window,
            other_conjuncts=tuple(clear_locations(conjunct) for conjunct in where.other_conjuncts),
        ),
    )


def _value_refusal(shape: _SqlShape, value_column: str) -> str | None:
    if value_column == shape.bucket_alias:
        return "value_column"
    if not any(_output_name(item) == value_column for item in shape.select.select):
        return "value_column"
    return None


def _with_where(shape: _SqlShape, *extra: ast.Expr) -> ast.SelectQuery:
    select = clone_expr(shape.select)
    select.order_by = None
    select.limit = None
    conjuncts = [*shape.where.other_conjuncts, *extra]
    select.where = None if not conjuncts else conjuncts[0] if len(conjuncts) == 1 else ast.And(exprs=conjuncts)
    return select


def _eligibility_refusal(shape: _SqlShape) -> str | None:
    key = shape.bucket_alias
    result = check_incremental_eligibility(
        _with_where(shape).to_hogql(), IncrementalConfig(incremental_key=key, unique_key=(key,))
    )
    if not result.eligible:
        return "ineligible"
    if result.warnings:
        return "nondeterministic"
    return None


def _timezone_refusal(shape: _SqlShape, team: Team, range_start: datetime, range_end: datetime) -> str | None:
    if shape.hourly:
        if not is_integer_timezone(team.timezone):
            return "timezone"
        tz = ZoneInfo(team.timezone)
        days = [(range_start + timedelta(days=i)).astimezone(tz) for i in range((range_end - range_start).days + 1)]
        return "dst_transition" if crosses_dst(days) else None
    if shape.utc_bucket or team.timezone == "UTC":
        return None
    return "timezone"


def _midnight(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def _window_start(window: _Window, team: Team, now_utc: datetime) -> datetime:
    if window.anchor == "today":
        local_now = now_utc.astimezone(ZoneInfo(team.timezone))
        anchor = min(_midnight(local_now), _midnight(now_utc))
    else:
        anchor = now_utc
    return (anchor - window.lookback).astimezone(UTC)


def _placeholder(name: str) -> ast.Placeholder:
    return ast.Placeholder(expr=ast.Field(chain=[name]))


def _insert_query(shape: _SqlShape, value_column: str) -> ast.SelectQuery:
    timestamp = shape.where.window.timestamp
    source = _with_where(
        shape,
        ast.CompareOperation(op=ast.CompareOperationOp.GtEq, left=timestamp, right=_placeholder("time_window_min")),
        ast.CompareOperation(op=ast.CompareOperationOp.Lt, left=timestamp, right=_placeholder("time_window_max")),
    )
    return ast.SelectQuery(
        select=[
            ast.Alias(
                alias="time_window_start",
                expr=ast.Call(
                    name="toDateTime",
                    args=[ast.Field(chain=[SOURCE_ALIAS, shape.bucket_alias]), ast.Constant(value="UTC")],
                ),
            ),
            ast.Alias(alias="series_key", expr=ast.Constant(value=value_column)),
            ast.Alias(
                alias="value",
                expr=ast.Call(
                    name="ifNull",
                    args=[
                        ast.Call(name="toFloat", args=[ast.Field(chain=[SOURCE_ALIAS, value_column])]),
                        ast.Constant(value=0),
                    ],
                ),
            ),
        ],
        select_from=ast.JoinExpr(table=source, alias=SOURCE_ALIAS),
    )


def _read_values(
    team: Team, *, job_ids: list[str], value_column: str, start: datetime, end: datetime
) -> dict[datetime, float]:
    sql = f"""
SELECT time_window_start, value
FROM {DISTRIBUTED_SERIES_VALUES_PREAGGREGATED_TABLE()}
WHERE team_id = %(team_id)s AND job_id IN %(job_ids)s AND series_key = %(series_key)s
  AND time_window_start >= %(range_start)s AND time_window_start < %(range_end)s
"""
    with tags_context(query_type="sql_series_values_read"):
        rows = sync_execute(
            sql,
            {
                "team_id": team.pk,
                "job_ids": tuple(job_ids),
                "series_key": value_column,
                "range_start": start,
                "range_end": end,
            },
            settings=READ_SETTINGS,
            workload=Workload.OFFLINE,
            team_id=team.pk,
        )
    return {
        bucket.astimezone(UTC) if bucket.tzinfo else bucket.replace(tzinfo=UTC): float(value) for bucket, value in rows
    }


def closed_sql_series_values(
    team: Team,
    query: HogQLQuery,
    *,
    value_column: str,
    run_inserts: bool,
    wait_timeout_seconds: float | None = None,
) -> ClosedSqlSeriesValues | SeriesValuesUnavailable:
    reason = _query_refusal(query)
    shape = _shape(query.query) if reason is None else reason
    if isinstance(shape, str):
        return SeriesValuesUnavailable(reason=shape)
    reason = _value_refusal(shape, value_column) or _eligibility_refusal(shape)
    if reason is not None:
        return SeriesValuesUnavailable(reason=reason)

    now_utc = datetime.now(UTC)
    range_end = _midnight(now_utc)
    range_start = _midnight(_window_start(shape.where.window, team, now_utc))
    if range_start >= range_end:
        return SeriesValuesUnavailable(reason="nothing_closed")
    if (range_end - range_start).days > MAX_RANGE_DAYS:
        return SeriesValuesUnavailable(reason="date_range_too_long")
    reason = _timezone_refusal(shape, team, range_start, range_end)
    if reason is None and team_has_property_access_rules(team_id=team.pk):
        reason = "property_access_rules"
    if reason is not None:
        return SeriesValuesUnavailable(reason=reason)

    insert_query = _insert_query(shape, value_column)
    modifiers = create_default_modifiers_for_team(team)
    database = Database.create_for(team.pk, team=team, modifiers=modifiers, bypass_warehouse_access_control=True)
    # The build runs with no user, so this check on the compiled INSERT, not the shape checks above, limits what it reads.
    reason = _compiled_read_refusal(
        insert_query, _source_alias(shape.select), team, database, modifiers, (range_start, range_end)
    )
    if reason is not None:
        return SeriesValuesUnavailable(reason=reason)

    result = ensure_precomputed(
        team=team,
        insert_query=insert_query,
        time_range_start=range_start,
        time_range_end=range_end,
        ttl_seconds=ttl_schedule(team.timezone),
        table=LazyComputationTable.SERIES_VALUES_PREAGGREGATED,
        query_type="sql_series_values_insert",
        run_inserts=run_inserts,
        wait_timeout_seconds=wait_timeout_seconds,
        read_after_write=run_inserts,
        cache_key_context={"engine": ENGINE_VERSION, "value_column": value_column},
        insert_settings=insert_time_cap(wait_timeout_seconds),
        database=database,
    )
    if not result.ready or not result.job_ids:
        return SeriesValuesUnavailable(reason="not_ready")
    values = _read_values(
        team,
        job_ids=[str(job_id) for job_id in result.job_ids],
        value_column=value_column,
        start=range_start,
        end=range_end,
    )
    return ClosedSqlSeriesValues(
        bucket_column=shape.bucket_alias, values=values, closed_before=range_end, freshly_built=result.freshly_built
    )
