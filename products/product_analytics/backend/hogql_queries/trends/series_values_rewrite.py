"""Reads the finished part of an hourly or daily event count from stored series values.

The rewrite matches the innermost query that Trends generates for a count series:

    SELECT count() AS total, toStartOfDay(timestamp) AS day_start
    FROM events AS e
    WHERE and(timestamp >= <lower>, timestamp <= <upper>, event = '<event>', <event property filters>)
    GROUP BY day_start

and replaces it with the stored whole hours UNION ALL the same query for the hours that are not stored:
today, and the hour that holds the upper bound. A SELECT around the two sums `total` per `day_start`, so
the query around the rewrite still gets one row per bucket.
"""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import field
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperationOp
from posthog.hogql.compilation import compilation_budget
from posthog.hogql.context import HogQLContext
from posthog.hogql.query import hogql_select_rewrite
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.dataclasses import frozen

from products.access_control.backend.facade.api import team_has_property_access_rules
from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationTable,
    ServedWindow,
    ensure_precomputed,
    parse_ttl_schedule,
)
from products.product_analytics.backend.facade.contracts import (
    PrecomputedSeriesValues,
    SeriesValuesBlocker as Blocker,
    SeriesValuesFeature as Feature,
    SeriesValuesUnavailable,
)
from products.product_analytics.backend.hogql_queries.trends.trends_query_runner import TrendsQueryRunner

INSERT_QUERY_TEMPLATE = """
SELECT
    hour AS time_window_start,
    hour + toIntervalHour(1) AS time_window_end,
    '' AS series_key,
    toFloat(count()) AS value
FROM (
    SELECT toStartOfHour(timestamp) AS hour
    FROM events
    WHERE and(
        timestamp >= {time_window_min},
        timestamp < {time_window_max},
        {filters}
    )
)
GROUP BY hour
"""

# How long a stored window stays fresh. The key is how far back the window starts, counted in whole days
# from the start of today in the team timezone: within one day, within four days, then everything older.
# Late events still change recent days, so a recent window is rebuilt often and an old one is kept for weeks.
TTL_SECONDS: dict[str, int] = {
    "1d": 6 * 60 * 60,
    "4d": 24 * 60 * 60,
    "default": 35 * 24 * 60 * 60,
}
# One build job covers at most this many days. A long range then builds as several short INSERTs, and
# an expired or failed job rebuilds only its own days.
MAX_WINDOW_DAYS = 7
# A window that was built sooner than this after it ended is rebuilt once the time has passed, because
# events for it can still arrive.
LATE_EVENTS_SETTLING_SECONDS = 60 * 60
# A longer range is declined, so one query cannot start an unbounded number of build jobs. The limit is
# the days of a leap year.
MAX_RANGE_DAYS = 366

# The build runs while the query compiles, and compilation has its own time limit. The build stops this
# long before that limit, which leaves time to print the rewritten query.
COMPILATION_MARGIN_SECONDS = 10

_BUCKET_FUNCTIONS = {"toStartOfDay", "toStartOfHour"}
# The functions a filter may call: the ones a standard event property filter prints. Each gives the same
# answer whenever it runs. A stored value is counted once and read for weeks, so a filter that reads the
# clock, a date that may be relative, or something the project can edit, such as an action, is declined.
_PURE_FILTER_FUNCTIONS = {
    "and",
    "or",
    "not",
    "ifnull",
    "isnull",
    "isnotnull",
    "match",
    "multisearchanycaseinsensitive",
    "sortablesemver",
    "tofloat",
    "tostring",
}
_INTERVAL_FLOORS = {"toIntervalDay": "day", "toIntervalHour": "hour"}

RewriteMode = Literal["serve", "stored_only"]


class _Declined(Exception):
    def __init__(self, blocker: Blocker) -> None:
        super().__init__(blocker.value)
        self.blocker = blocker


def _is_field(expr: ast.Expr | None, name: str) -> bool:
    return isinstance(expr, ast.Field) and [str(part) for part in expr.chain] == [name]


def _is_event_name(condition: ast.Expr) -> bool:
    return (
        isinstance(condition, ast.CompareOperation)
        and condition.op == CompareOperationOp.Eq
        and _is_field(condition.left, "event")
        and isinstance(condition.right, ast.Constant)
    )


class _ConditionReads(TraversingVisitor):
    def __init__(self) -> None:
        self.roots: set[str] = set()
        self.has_subquery = False
        self.calls: set[str] = set()

    def visit_field(self, node: ast.Field) -> None:
        self.roots.add(str(node.chain[0]))

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.has_subquery = True

    def visit_call(self, node: ast.Call) -> None:
        self.calls.add(node.name.lower())
        super().visit_call(node)


def _reads_only_event_properties(condition: ast.Expr) -> bool:
    reads = _ConditionReads()
    reads.visit(condition)
    return not reads.has_subquery and reads.calls <= _PURE_FILTER_FUNCTIONS and reads.roots == {"properties"}


# Kinds of filter the stored build reproduces, because an event's name and properties never change after
# ingestion. A condition that none of them accepts declines the query. A comparison is reported for each
# kind a query used, so a new kind can be watched on its own before it is trusted.
_FILTER_FEATURES: dict[Feature, Callable[[ast.Expr], bool]] = {
    Feature.EVENT_NAME: _is_event_name,
    Feature.EVENT_PROPERTY_FILTERS: _reads_only_event_properties,
}


def _constant_instant(expr: ast.Expr, timezone: ZoneInfo) -> datetime | None:
    floor: str | None = None
    if isinstance(expr, ast.Call) and expr.name == "toStartOfInterval" and len(expr.args) == 2:
        interval = expr.args[1]
        if not (isinstance(interval, ast.Call) and interval.name in _INTERVAL_FLOORS and len(interval.args) == 1):
            return None
        if not (isinstance(interval.args[0], ast.Constant) and interval.args[0].value == 1):
            return None
        floor = _INTERVAL_FLOORS[interval.name]
        expr = expr.args[0]
    if isinstance(expr, ast.Call) and expr.name == "assumeNotNull" and len(expr.args) == 1:
        expr = expr.args[0]
    if not (isinstance(expr, ast.Call) and expr.name == "toDateTime" and len(expr.args) == 1):
        return None
    literal = expr.args[0]
    if not (isinstance(literal, ast.Constant) and isinstance(literal.value, str)):
        return None
    try:
        local = datetime.strptime(literal.value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone)
    except ValueError:
        return None
    if floor == "day":
        local = local.replace(hour=0, minute=0, second=0)
    elif floor == "hour":
        local = local.replace(minute=0, second=0)
    # A wall-clock time that a clock change skips or repeats has two readings, and ClickHouse may take the other one.
    if local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset():
        return None
    return local.astimezone(UTC)


def _conditions(where: ast.Expr | None) -> list[ast.Expr] | None:
    if isinstance(where, ast.And):
        return where.exprs
    if isinstance(where, ast.Call) and where.name == "and":
        return where.args
    return None


@frozen
class _CountQuery:
    columns: list[str]
    bucket_function: str
    lower: datetime
    lower_index: int
    upper: datetime
    filters: list[ast.Expr]
    features: frozenset[Feature]


def _match(node: ast.SelectQuery, timezone: ZoneInfo) -> _CountQuery | Blocker | None:
    """A count query, the reason a Trends series query is not one, or None for any other query."""
    table = node.select_from
    if table is None or not _is_field(table.table, "events"):
        return None
    aliases = {expr.alias: expr.expr for expr in node.select if isinstance(expr, ast.Alias)}
    total, bucket = aliases.get("total"), aliases.get("day_start")
    if total is None or bucket is None:
        return None

    if "breakdown_value" in aliases:
        return Blocker.BREAKDOWN
    if not (
        isinstance(bucket, ast.Call)
        and bucket.name in _BUCKET_FUNCTIONS
        and len(bucket.args) == 1
        and _is_field(bucket.args[0], "timestamp")
    ):
        return Blocker.OTHER_INTERVAL
    if not (isinstance(total, ast.Call) and total.name == "count" and not total.args and not total.distinct):
        return Blocker.OTHER_AGGREGATE
    if table.sample is not None and not table.sample.samples_all_rows():
        return Blocker.SAMPLING
    other_clauses = (
        table.next_join,
        node.ctes,
        node.distinct,
        node.array_join_op,
        node.window_exprs,
        node.prewhere,
        node.having,
        node.qualify,
        node.group_by_mode,
        node.limit,
        node.limit_by,
        node.offset,
    )
    # The executor gives every top-level query a limit before the rewrite runs, so only a subquery matches.
    if len(node.select) != 2 or any(other_clauses):
        return Blocker.UNSUPPORTED_CLAUSE
    if not (node.group_by and len(node.group_by) == 1 and _is_field(node.group_by[0], "day_start")):
        return Blocker.UNSUPPORTED_CLAUSE
    conditions = _conditions(node.where)
    if conditions is None:
        return Blocker.UNSUPPORTED_TIME_RANGE

    lower: datetime | None = None
    lower_index = -1
    upper: datetime | None = None
    filters: list[ast.Expr] = []
    features: set[Feature] = set()
    for index, condition in enumerate(conditions):
        if isinstance(condition, ast.CompareOperation) and _is_field(condition.left, "timestamp"):
            instant = _constant_instant(condition.right, timezone)
            if instant is None:
                return Blocker.UNSUPPORTED_TIME_RANGE
            if condition.op == CompareOperationOp.GtEq and lower is None:
                lower, lower_index = instant, index
            elif condition.op == CompareOperationOp.LtEq and upper is None:
                upper = instant
            else:
                return Blocker.UNSUPPORTED_TIME_RANGE
            continue
        feature = next((feature for feature, accepts in _FILTER_FEATURES.items() if accepts(condition)), None)
        if feature is None:
            return Blocker.UNSUPPORTED_FILTER
        filters.append(condition)
        features.add(feature)
    if lower is None or upper is None:
        return Blocker.UNSUPPORTED_TIME_RANGE
    return _CountQuery(
        columns=[expr.alias for expr in node.select if isinstance(expr, ast.Alias)],
        bucket_function=bucket.name,
        lower=lower,
        lower_index=lower_index,
        upper=upper,
        filters=filters,
        features=frozenset(features),
    )


class _EventsReads(TraversingVisitor):
    def __init__(self) -> None:
        self.found = False

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if _is_field(node.table, "events"):
            self.found = True
        super().visit_join_expr(node)


def _covers(windows: tuple[ServedWindow, ...], start: datetime, end: datetime) -> bool:
    covered_until = start
    for window in sorted(windows, key=lambda window: window.start):
        if window.start > covered_until:
            return False
        covered_until = max(covered_until, window.end)
    return covered_until >= end


def _hour_start(instant: datetime) -> datetime:
    return instant.replace(minute=0, second=0, microsecond=0)


def _has_whole_hour_offsets(timezone: str, years: set[int]) -> bool:
    # Checked in January and in July of each year the range touches, because one zone is a whole hour
    # from UTC for only half the year.
    zone = ZoneInfo(timezone)
    offsets = [datetime(year, month, 1, tzinfo=zone).utcoffset() for year in years for month in (1, 7)]
    return all(offset is not None and offset.total_seconds() % 3600 == 0 for offset in offsets)


def _stored_select(query: _CountQuery, job_ids: list[str], until: datetime) -> ast.SelectQuery:
    conditions: list[ast.Expr] = [
        ast.CompareOperation(
            op=CompareOperationOp.In, left=ast.Field(chain=["job_id"]), right=ast.Constant(value=job_ids)
        ),
        ast.CompareOperation(
            op=CompareOperationOp.GtEq,
            left=ast.Field(chain=["time_window_start"]),
            right=ast.Constant(value=query.lower),
        ),
        ast.CompareOperation(
            op=CompareOperationOp.LtEq, left=ast.Field(chain=["time_window_end"]), right=ast.Constant(value=until)
        ),
        # A row without a window end has the zero date there. Leaving it out shows a writer that forgot the column
        # as missing values.
        ast.CompareOperation(
            op=CompareOperationOp.Gt,
            left=ast.Field(chain=["time_window_end"]),
            right=ast.Field(chain=["time_window_start"]),
        ),
    ]
    columns: dict[str, ast.Expr] = {
        "total": ast.Call(name="toInt", args=[ast.Call(name="sum", args=[ast.Field(chain=["value"])])]),
        "day_start": ast.Call(name=query.bucket_function, args=[ast.Field(chain=["time_window_start"])]),
    }
    return ast.SelectQuery(
        # A UNION ALL pairs columns by position, so the stored side keeps the order of the live side.
        select=[ast.Alias(alias=column, expr=columns[column]) for column in query.columns],
        select_from=ast.JoinExpr(table=ast.Field(chain=["posthog", "series_values_preaggregated"])),
        where=ast.And(exprs=conditions),
        group_by=[ast.Field(chain=["day_start"])],
    )


@frozen(frozen=False)
class SeriesValuesRewrite:
    """One caller's rewrite of the queries it runs, and what the rewrite did with them.

    "serve" reads finished hours from stored values and the rest from events, and leaves a query it declines
    alone. "stored_only" reads no events: it raises for a query that it cannot answer from stored values alone,
    so a shadow run never repeats a live scan.
    """

    mode: RewriteMode
    # A `time.monotonic()` value. No build starts after it, and a build waits no longer than until it.
    deadline: float | None = None
    today_start: datetime = field(
        default_factory=lambda: datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    )
    features: set[Feature] = field(default_factory=set)
    declined: list[Blocker] = field(default_factory=list)
    # One entry per rewritten count query: whether its values were built for this call.
    built: list[bool] = field(default_factory=list)

    def rewrite(
        self, node: ast.SelectQuery | ast.SelectSetQuery, context: HogQLContext
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        rewriter = _Rewriter(self, context)
        rewritten = rewriter.visit(node)
        if self.mode == "stored_only":
            reads = _EventsReads()
            reads.visit(rewritten)
            if reads.found or not rewriter.count_queries:
                raise _Declined(Blocker.NO_COUNT_QUERY)
        return rewritten


class _Rewriter(CloningVisitor):
    def __init__(self, request: SeriesValuesRewrite, context: HogQLContext) -> None:
        super().__init__()
        self.request = request
        self.context = context
        self.count_queries = 0

    def _decline(self, blocker: Blocker, node: ast.SelectQuery) -> ast.SelectQuery:
        if self.request.mode == "stored_only":
            raise _Declined(blocker)
        self.request.declined.append(blocker)
        return node

    def _build_deadline(self) -> float | None:
        deadlines = [self.request.deadline]
        budget = compilation_budget.get()
        if budget is not None:
            deadlines.append(budget.deadline - COMPILATION_MARGIN_SECONDS)
        known = [deadline for deadline in deadlines if deadline is not None]
        return min(known) if known else None

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        cloned = super().visit_select_query(node)
        team = self.context.team
        if team is None:
            return cloned
        query = _match(cloned, ZoneInfo(team.timezone))
        if query is None:
            return cloned
        if isinstance(query, Blocker):
            return self._decline(query, cloned)
        modifiers = self.context.modifiers
        years = {query.lower.year, query.upper.year}
        if not _has_whole_hour_offsets(team.timezone, years) or (
            modifiers and modifiers.convertToProjectTimezone is False
        ):
            return self._decline(Blocker.TIMEZONE, cloned)
        if team_has_property_access_rules(team_id=team.pk):
            return self._decline(Blocker.PROPERTY_ACCESS_RULES, cloned)

        # The upper bound is a whole second and `timestamp` has microseconds, so the live query leaves out
        # the rest of that second. A stored hour cannot, so the hour that holds the upper bound stays live.
        stored_until = min(self.request.today_start, _hour_start(query.upper))
        if query.lower != _hour_start(query.lower):
            return self._decline(Blocker.PARTIAL_HOUR, cloned)
        if query.lower >= stored_until:
            return self._decline(Blocker.NO_FINISHED_BUCKET, cloned)
        jobs_start = query.lower.replace(hour=0)
        jobs_end = stored_until if stored_until.hour == 0 else stored_until.replace(hour=0) + timedelta(days=1)
        if (jobs_end - jobs_start).days > MAX_RANGE_DAYS:
            return self._decline(Blocker.DATE_RANGE_TOO_LONG, cloned)

        deadline = self._build_deadline()
        seconds_left = None if deadline is None else deadline - time.monotonic()
        if seconds_left is not None and seconds_left <= 0:
            return self._decline(Blocker.NOT_READY, cloned)
        filters = [clone_expr(condition) for condition in query.filters]
        # The build compiles queries of its own, which must reach ClickHouse as the executor wrote them.
        hook = hogql_select_rewrite.set(None)
        try:
            result = ensure_precomputed(
                team=team,
                insert_query=INSERT_QUERY_TEMPLATE,
                time_range_start=jobs_start,
                time_range_end=jobs_end,
                ttl_seconds=parse_ttl_schedule(
                    TTL_SECONDS,
                    team.timezone,
                    max_window_days=MAX_WINDOW_DAYS,
                    settling_period_seconds=LATE_EVENTS_SETTLING_SECONDS,
                ),
                table=LazyComputationTable.SERIES_VALUES_PREAGGREGATED,
                placeholders={"filters": ast.And(exprs=filters) if filters else ast.Constant(value=True)},
                query_type="series_values_insert",
                run_inserts=True,
                wait_timeout_seconds=seconds_left,
                read_after_write=True,
                cache_key_context={"engine": "series_values_v1"},
            )
        finally:
            hogql_select_rewrite.reset(hook)
        # A job can expire while the executor collects its result. A day that no returned job covers would
        # read as zero.
        if not result.ready or not result.job_ids or not _covers(result.served_windows, jobs_start, jobs_end):
            return self._decline(Blocker.NOT_READY, cloned)

        self.count_queries += 1
        self.request.features.update(query.features)
        self.request.built.append(result.freshly_built)
        stored = _stored_select(query, [str(job_id) for job_id in result.job_ids], stored_until)
        if self.request.mode == "stored_only":
            return stored

        live = cloned
        count = live.select[query.columns.index("total")]
        assert isinstance(count, ast.Alias)
        # Both sides of a UNION ALL need one type for `total`.
        count.expr = ast.Call(name="toInt", args=[count.expr])
        conditions = _conditions(live.where)
        assert conditions is not None
        conditions[query.lower_index] = ast.CompareOperation(
            op=CompareOperationOp.GtEq, left=ast.Field(chain=["timestamp"]), right=ast.Constant(value=stored_until)
        )
        parts = ast.SelectSetQuery(
            initial_select_query=stored,
            subsequent_select_queries=[ast.SelectSetNode(select_query=live, set_operator="UNION ALL")],
        )
        # The bucket at the boundary has a stored row and a live row. The query around this one may take a
        # maximum or an average of `total`, so it has to get one row per bucket, as it does from the live query.
        columns: dict[str, ast.Expr] = {
            "total": ast.Call(name="sum", args=[ast.Field(chain=["total"])]),
            "day_start": ast.Field(chain=["day_start"]),
        }
        return ast.SelectQuery(
            select=[ast.Alias(alias=column, expr=columns[column]) for column in query.columns],
            select_from=ast.JoinExpr(table=parts),
            group_by=[ast.Field(chain=["day_start"])],
        )


@contextmanager
def rewriting_series_values(
    mode: RewriteMode, *, wait_timeout_seconds: float | None = None
) -> Iterator[SeriesValuesRewrite]:
    # One deadline for every build the caller's queries start, so together they cannot outlast its budget.
    deadline = None if wait_timeout_seconds is None else time.monotonic() + wait_timeout_seconds
    request = SeriesValuesRewrite(mode=mode, deadline=deadline)
    token = hogql_select_rewrite.set(request.rewrite)
    try:
        yield request
    finally:
        hogql_select_rewrite.reset(token)


def _finished_buckets(runner: TrendsQueryRunner, today_start: datetime) -> set[datetime]:
    buckets = runner.query_date_range.all_values()
    date_to = runner.query_date_range.date_to()
    stored_until = min(today_start, _hour_start(date_to.astimezone(UTC)))
    ends = [*buckets[1:], date_to + timedelta(microseconds=1)]
    return {bucket.replace(tzinfo=None) for bucket, end in zip(buckets, ends) if end <= stored_until}


def precomputed_series_values(
    runner: TrendsQueryRunner, *, wait_timeout_seconds: float | None = None
) -> PrecomputedSeriesValues | SeriesValuesUnavailable:
    with rewriting_series_values("stored_only", wait_timeout_seconds=wait_timeout_seconds) as request:
        finished = _finished_buckets(runner, request.today_start)
        if not finished:
            return SeriesValuesUnavailable(reason=Blocker.NO_FINISHED_BUCKET)
        try:
            results = runner.calculate().results
        except _Declined as declined:
            return SeriesValuesUnavailable(reason=declined.blocker)
    if not results:
        return SeriesValuesUnavailable(reason=Blocker.NO_COUNT_QUERY)
    series = results[0]
    return PrecomputedSeriesValues(
        values={
            bucket: value
            for day, value in zip(series["days"], series["data"])
            if (bucket := datetime.fromisoformat(day)) in finished
        },
        freshly_built=any(request.built),
        features=frozenset(request.features),
    )
