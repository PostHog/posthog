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

import math
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import field
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import ClassVar, Literal
from zoneinfo import ZoneInfo

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperationOp
from posthog.hogql.compilation import compilation_budget
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.query import hogql_select_rewrite
from posthog.hogql.transforms.flag_calls_from_flag_evaluations import names_flag_called_event
from posthog.hogql.transforms.preaggregated_table_transformation import is_integer_timezone
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.dataclasses import frozen
from posthog.models.team import Team

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


class _ConditionReads(TraversingVisitor):
    def __init__(self) -> None:
        self.roots: set[str] = set()
        self.has_subquery = False
        self.calls: set[str] = set()

    def visit_field(self, node: ast.Field) -> None:
        self.roots.add(str(node.chain[0]))

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.has_subquery = True

    def visit_hogqlx_tag(self, node: ast.HogQLXTag) -> None:
        # A query tag holds its SQL in a string attribute and only becomes a subquery when it is resolved.
        self.has_subquery = True

    def visit_call(self, node: ast.Call) -> None:
        self.calls.add(node.name.lower())
        super().visit_call(node)


class _EventsReads(TraversingVisitor):
    def __init__(self) -> None:
        self.found = False

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if _is_field(node.table, "events"):
            self.found = True
        super().visit_join_expr(node)


class _FilterFeature(ABC):
    """A kind of filter the stored build reproduces, because what it reads never changes after ingestion.

    A condition that no kind accepts declines the query. A comparison is reported for each kind a query
    used, so a new kind can be watched on its own before it is trusted.
    """

    feature: ClassVar[Feature]

    @abstractmethod
    def accepts(self, condition: ast.Expr) -> bool: ...


class _EventName(_FilterFeature):
    feature = Feature.EVENT_NAME

    def accepts(self, condition: ast.Expr) -> bool:
        return (
            isinstance(condition, ast.CompareOperation)
            and condition.op == CompareOperationOp.Eq
            and _is_field(condition.left, "event")
            and isinstance(condition.right, ast.Constant)
        )


class _EventPropertyFilters(_FilterFeature):
    feature = Feature.EVENT_PROPERTY_FILTERS

    def accepts(self, condition: ast.Expr) -> bool:
        reads = _ConditionReads()
        reads.visit(condition)
        return not reads.has_subquery and reads.calls <= _PURE_FILTER_FUNCTIONS and reads.roots == {"properties"}


_FILTER_FEATURES: tuple[_FilterFeature, ...] = (_EventName(), _EventPropertyFilters())


@frozen
class _JobRange:
    start: datetime
    end: datetime


@frozen
class _CountQuery:
    """The count query that Trends generates for one series, reduced to what the rewrite needs."""

    columns: list[str]
    bucket_function: str
    lower: datetime
    lower_index: int
    upper: datetime
    filters: list[ast.Expr]
    features: frozenset[Feature]

    @classmethod
    def match(cls, node: ast.SelectQuery, timezone: ZoneInfo) -> "_CountQuery | Blocker | None":
        """The count query in `node`, the reason a Trends series query is not one, or None for any other query."""
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
            # The table that flag calls are read from follows the organization's flag evaluations mode, which
            # is not part of a stored job's identity. A stored count of them would outlive a change of mode.
            if names_flag_called_event(condition):
                return Blocker.UNSUPPORTED_FILTER
            feature = next((kind.feature for kind in _FILTER_FEATURES if kind.accepts(condition)), None)
            if feature is None:
                return Blocker.UNSUPPORTED_FILTER
            filters.append(condition)
            features.add(feature)
        if lower is None or upper is None:
            return Blocker.UNSUPPORTED_TIME_RANGE
        return cls(
            columns=[expr.alias for expr in node.select if isinstance(expr, ast.Alias)],
            bucket_function=bucket.name,
            lower=lower,
            lower_index=lower_index,
            upper=upper,
            filters=filters,
            features=frozenset(features),
        )

    def stored_until(self, today_start: datetime) -> datetime:
        # The upper bound is a whole second and `timestamp` has microseconds, so the live query leaves out
        # the rest of that second. A stored hour cannot, so the hour that holds the upper bound stays live.
        return min(today_start, _hour_start(self.upper))

    def job_range(self, stored_until: datetime) -> _JobRange:
        """The whole UTC days that hold the stored hours. A build job covers whole days."""
        start = self.lower.replace(hour=0)
        end = stored_until if stored_until.hour == 0 else stored_until.replace(hour=0) + timedelta(days=1)
        return _JobRange(start=start, end=end)

    def stored_select(self, job_ids: list[str], until: datetime) -> ast.SelectQuery:
        conditions: list[ast.Expr] = [
            ast.CompareOperation(
                op=CompareOperationOp.In, left=ast.Field(chain=["job_id"]), right=ast.Constant(value=job_ids)
            ),
            ast.CompareOperation(
                op=CompareOperationOp.GtEq,
                left=ast.Field(chain=["time_window_start"]),
                right=ast.Constant(value=self.lower),
            ),
            ast.CompareOperation(
                op=CompareOperationOp.LtEq, left=ast.Field(chain=["time_window_end"]), right=ast.Constant(value=until)
            ),
            # A row without a window end has the zero date there. Leaving it out shows a writer that forgot the
            # column as missing values.
            ast.CompareOperation(
                op=CompareOperationOp.Gt,
                left=ast.Field(chain=["time_window_end"]),
                right=ast.Field(chain=["time_window_start"]),
            ),
        ]
        columns: dict[str, ast.Expr] = {
            "total": ast.Call(name="toInt", args=[ast.Call(name="sum", args=[ast.Field(chain=["value"])])]),
            "day_start": ast.Call(name=self.bucket_function, args=[ast.Field(chain=["time_window_start"])]),
        }
        return ast.SelectQuery(
            # A UNION ALL pairs columns by position, so the stored side keeps the order of the live side.
            select=[ast.Alias(alias=column, expr=columns[column]) for column in self.columns],
            select_from=ast.JoinExpr(table=ast.Field(chain=["posthog", "series_values_preaggregated"])),
            where=ast.And(exprs=conditions),
            group_by=[ast.Field(chain=["day_start"])],
        )

    def union_with_live(
        self, stored: ast.SelectQuery, live: ast.SelectQuery, stored_until: datetime
    ) -> ast.SelectQuery:
        """`stored`, plus `live` narrowed to the hours from `stored_until` on, as one row per bucket."""
        count = live.select[self.columns.index("total")]
        assert isinstance(count, ast.Alias)
        # Both sides of a UNION ALL need one type for `total`.
        count.expr = ast.Call(name="toInt", args=[count.expr])
        conditions = _conditions(live.where)
        assert conditions is not None
        conditions[self.lower_index] = ast.CompareOperation(
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
            select=[ast.Alias(alias=column, expr=columns[column]) for column in self.columns],
            select_from=ast.JoinExpr(table=parts),
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

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        cloned = super().visit_select_query(node)
        team = self.context.team
        if team is None:
            return cloned
        query = _CountQuery.match(cloned, ZoneInfo(team.timezone))
        if query is None:
            return cloned
        if isinstance(query, Blocker):
            return self._decline(query, cloned)
        stored_until = query.stored_until(self.request.today_start)
        blocker = self._blocker(query, team, stored_until)
        if blocker is not None:
            return self._decline(blocker, cloned)
        job_ids = self._build(query, team, stored_until)
        if job_ids is None:
            return self._decline(Blocker.NOT_READY, cloned)
        stored = query.stored_select(job_ids, stored_until)
        if self.request.mode == "stored_only":
            return stored
        return query.union_with_live(stored, cloned, stored_until)

    def _decline(self, blocker: Blocker, node: ast.SelectQuery) -> ast.SelectQuery:
        self.request.declined.append(blocker)
        if self.request.mode == "stored_only":
            raise _Declined(blocker)
        return node

    def _blocker(self, query: _CountQuery, team: Team, stored_until: datetime) -> Blocker | None:
        modifiers = self.context.modifiers
        # Stored rows are UTC hours, so they only add up into local hours and days in a zone that is a
        # whole hour from UTC.
        if not is_integer_timezone(team.timezone) or (modifiers and modifiers.convertToProjectTimezone is False):
            return Blocker.TIMEZONE
        if team_has_property_access_rules(team_id=team.pk):
            return Blocker.PROPERTY_ACCESS_RULES
        if query.lower != _hour_start(query.lower):
            return Blocker.PARTIAL_HOUR
        if query.lower >= stored_until:
            return Blocker.NO_FINISHED_BUCKET
        jobs = query.job_range(stored_until)
        if (jobs.end - jobs.start).days > MAX_RANGE_DAYS:
            return Blocker.DATE_RANGE_TOO_LONG
        return None

    def _build_deadline(self) -> float | None:
        deadlines = [self.request.deadline]
        budget = compilation_budget.get()
        if budget is not None:
            deadlines.append(budget.deadline - COMPILATION_MARGIN_SECONDS)
        known = [deadline for deadline in deadlines if deadline is not None]
        return min(known) if known else None

    def _build(self, query: _CountQuery, team: Team, stored_until: datetime) -> list[str] | None:
        """Makes sure the stored hours exist. Returns the jobs that hold them, or None when they are not ready."""
        # The series of one query run in parallel. Once one of them is declined the whole call is, so the
        # others start no build.
        if self.request.mode == "stored_only" and self.request.declined:
            raise _Declined(self.request.declined[0])
        deadline = self._build_deadline()
        seconds_left = None if deadline is None else deadline - time.monotonic()
        if seconds_left is not None and seconds_left <= 0:
            return None
        jobs = query.job_range(stored_until)
        filters = [clone_expr(condition) for condition in query.filters]
        ensure = partial(
            ensure_precomputed,
            team=team,
            insert_query=INSERT_QUERY_TEMPLATE,
            time_range_start=jobs.start,
            time_range_end=jobs.end,
            ttl_seconds=parse_ttl_schedule(
                TTL_SECONDS,
                team.timezone,
                max_window_days=MAX_WINDOW_DAYS,
                settling_period_seconds=LATE_EVENTS_SETTLING_SECONDS,
            ),
            table=LazyComputationTable.SERIES_VALUES_PREAGGREGATED,
            placeholders={"filters": ast.And(exprs=filters) if filters else ast.Constant(value=True)},
            query_type="series_values_insert",
            wait_timeout_seconds=seconds_left,
            read_after_write=True,
            cache_key_context={"engine": "series_values_v1"},
            # The wait only stops the next INSERT from starting. Without a limit of its own, an INSERT
            # that starts late runs on while the query waits to compile.
            insert_settings=None if seconds_left is None else {"max_execution_time": max(1, math.ceil(seconds_left))},
        )
        # The build compiles queries of its own, which must reach ClickHouse as the executor wrote them.
        hook = hogql_select_rewrite.set(None)
        try:
            # An INSERT is printed against the team's full database, which costs Postgres reads to build.
            # The first call only looks for stored values, so a query that finds them all builds no
            # database, and a build makes one database for all of its windows.
            result = ensure(run_inserts=False)
            if not result.ready:
                result = ensure(run_inserts=True, database=_insert_database(team))
        finally:
            hogql_select_rewrite.reset(hook)
        # A job can expire while the executor collects its result. A day that no returned job covers would
        # read as zero.
        if not result.ready or not result.job_ids or not _covers(result.served_windows, jobs):
            return None
        self.count_queries += 1
        self.request.features.update(query.features)
        self.request.built.append(result.freshly_built)
        return [str(job_id) for job_id in result.job_ids]


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


def precomputed_series_values(
    runner: TrendsQueryRunner, *, wait_timeout_seconds: float | None = None
) -> PrecomputedSeriesValues | SeriesValuesUnavailable:
    # The values returned are those of the first series, so a query with several is declined until a
    # caller can say which series it wants.
    if len(runner.query.series) > 1:
        return SeriesValuesUnavailable(reason=Blocker.MULTIPLE_SERIES)
    # An all-time range starts at the first event, which the runner has to look up, and it is longer than
    # the range limit for any project older than a year.
    if runner.query.dateRange and runner.query.dateRange.date_from == "all":
        return SeriesValuesUnavailable(reason=Blocker.ALL_TIME_RANGE)
    with rewriting_series_values("stored_only", wait_timeout_seconds=wait_timeout_seconds) as request:
        try:
            finished = _finished_buckets(runner, request.today_start)
            if not finished:
                return SeriesValuesUnavailable(reason=Blocker.NO_FINISHED_BUCKET)
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


def _finished_buckets(runner: TrendsQueryRunner, today_start: datetime) -> set[datetime]:
    buckets = runner.query_date_range.all_values()
    date_to = runner.query_date_range.date_to()
    stored_until = min(today_start, _hour_start(date_to.astimezone(UTC)))
    ends = [*buckets[1:], date_to + timedelta(microseconds=1)]
    return {bucket.replace(tzinfo=None) for bucket, end in zip(buckets, ends) if end <= stored_until}


def _is_field(expr: ast.Expr | None, name: str) -> bool:
    return isinstance(expr, ast.Field) and [str(part) for part in expr.chain] == [name]


def _conditions(where: ast.Expr | None) -> list[ast.Expr] | None:
    if isinstance(where, ast.And):
        return where.exprs
    if isinstance(where, ast.Call) and where.name == "and":
        return where.args
    return None


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


def _covers(windows: tuple[ServedWindow, ...], jobs: _JobRange) -> bool:
    covered_until = jobs.start
    for window in sorted(windows, key=lambda window: window.start):
        if window.start > covered_until:
            return False
        covered_until = max(covered_until, window.end)
    return covered_until >= jobs.end


def _insert_database(team: Team) -> Database:
    # What the executor builds for an INSERT when it gets no database: no user, warehouse access control
    # bypassed and the team's default modifiers. It resolves `events` as the live query does. The database
    # of built-in tables alone does not, because it never reads flag calls from `flag_evaluations`.
    return Database.create_for(
        team=team, modifiers=create_default_modifiers_for_team(team), bypass_warehouse_access_control=True
    )


def _hour_start(instant: datetime) -> datetime:
    return instant.replace(minute=0, second=0, microsecond=0)
