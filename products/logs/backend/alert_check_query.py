import time
import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from posthog.schema import (
    DateRange,
    FilterLogicalOperator,
    HogQLQueryModifiers,
    HogQLQueryResponse,
    IntervalType,
    LogsQuery,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import CloningVisitor

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team

from products.logs.backend.alert_utils import MAX_BYTES_TO_READ
from products.logs.backend.logs_query_runner import LIVE_LOGS_CHECKPOINT_QUERY, LogsFilterBuilder
from products.logs.backend.models import LogsAlertConfiguration


@dataclass(frozen=True)
class AlertCheckCountResult:
    count: int
    query_duration_ms: int


@dataclass(frozen=True)
class BucketedCount:
    timestamp: dt.datetime
    count: int


def _build_logs_query(alert: LogsAlertConfiguration, date_range: DateRange) -> LogsQuery:
    filters = alert.filters
    filter_group = filters.get("filterGroup")
    if filter_group:
        pg = PropertyGroupFilter.model_validate(filter_group)
    else:
        pg = PropertyGroupFilter(
            type=FilterLogicalOperator.AND_,
            values=[PropertyGroupFilterValue(type=FilterLogicalOperator.AND_, values=[])],
        )
    return LogsQuery(
        dateRange=date_range,
        serviceNames=filters.get("serviceNames") or [],
        severityLevels=filters.get("severityLevels") or [],
        filterGroup=pg,
        kind="LogsQuery",
    )


def _period_ranges(
    date_from: dt.datetime, period_minutes: int, period_count: int
) -> list[tuple[dt.datetime, dt.datetime]]:
    return [
        (
            date_from + dt.timedelta(minutes=i * period_minutes),
            date_from + dt.timedelta(minutes=(i + 1) * period_minutes),
        )
        for i in range(period_count)
    ]


def rolling_check_lookback_minutes(window_minutes: int, cadence_minutes: int, period_count: int) -> int:
    """Total minutes of history covered by M cadence-stepped rolling windows."""
    return window_minutes + (period_count - 1) * cadence_minutes


def _rolling_check_ranges(
    nca: dt.datetime,
    window_minutes: int,
    cadence_minutes: int,
    period_count: int,
) -> list[tuple[dt.datetime, dt.datetime]]:
    """M cadence-stepped rolling windows ending at NCA, oldest-first."""
    ranges: list[tuple[dt.datetime, dt.datetime]] = []
    for k in range(period_count - 1, -1, -1):
        end = nca - dt.timedelta(minutes=k * cadence_minutes)
        start = end - dt.timedelta(minutes=window_minutes)
        ranges.append((start, end))
    return ranges


def _timestamp_in_range(start: dt.datetime, end: dt.datetime) -> ast.Expr:
    # Compare raw `timestamp`, not `toStartOfMinute(timestamp)`: `date_from` can carry
    # sub-minute fractions from a DateTime64(6) checkpoint, and a minute-floor wrap
    # would drop up to 60s of data at the lower boundary.
    return parse_expr(
        "timestamp >= {start} AND timestamp < {end}",
        placeholders={"start": ast.Constant(value=start), "end": ast.Constant(value=end)},
    )


def _tag_alert_query(*, team: Team, alert_config_id: str, source: str) -> None:
    tag_queries(
        product=Product.LOGS,
        feature=Feature.ALERTING,
        source=source,
        alert_config_id=alert_config_id,
        team_id=str(team.id),
    )


def build_alert_where_expr(
    *,
    team: Team,
    alert: LogsAlertConfiguration,
    date_from: dt.datetime,
    date_to: dt.datetime,
) -> ast.Expr:
    """Build the per-alert WHERE expression used by both single-alert and batched queries.

    Adds explicit half-open timestamp bounds [date_from, date_to) on top of
    `LogsFilterBuilder.where()` so adjacent alert windows can't double-count
    logs at the boundary. `LogsFilterBuilder.where()` includes a `{filters}`
    placeholder that resolves to `true` when no HogQLFilters are passed to
    `execute_hogql_query`.
    """
    date_range = DateRange(date_from=date_from.isoformat(), date_to=date_to.isoformat())
    logs_query = _build_logs_query(alert, date_range)
    query_date_range = QueryDateRange(
        date_range=logs_query.dateRange,
        team=team,
        interval=IntervalType.MINUTE,
        interval_count=1,
        now=date_to,
        timezone_info=ZoneInfo("UTC"),
        exact_timerange=True,
    )
    base_where = LogsFilterBuilder(logs_query, team, query_date_range).where()
    return ast.And(
        exprs=[
            base_where,
            parse_expr(
                "timestamp >= {date_from} AND timestamp < {date_to}",
                placeholders={
                    "date_from": ast.Constant(value=date_from),
                    "date_to": ast.Constant(value=date_to),
                },
            ),
        ]
    )


class _StripIndexHints(CloningVisitor):
    """Return a copy of the expression with indexHint(...) calls replaced by true.

    indexHint always evaluates to 1; it exists only so index analysis sees the
    wrapped expression. See `BatchedAlertCheckQuery.__init__` for why the
    hoisted predicate copies must not carry it.
    """

    def visit_call(self, node: ast.Call) -> ast.Expr:
        if node.name == "indexHint":
            return ast.Constant(value=True)
        return super().visit_call(node)


def _strip_index_hints(expr: ast.Expr) -> ast.Expr:
    return _StripIndexHints().visit(expr)


class AlertCheckQuery:
    """Lightweight count query against the logs ClickHouse cluster for alert checks.

    Runs once per minute per alert, potentially for every org (~10K near-term),
    against a table ingesting ~10M rows/min. Uses the projection_aggregate_counts
    projection where possible and falls back to raw scans with bloom filter pruning
    for body/attribute filters. Intentionally not an AnalyticsQueryRunner — this is
    an internal query with its own timeout and byte limits, not user-facing.

    See the [Logs Alerting RFC](https://github.com/PostHog/requests-for-comments-internal/blob/main/engineering/2026-03-03-logs-alerting.md)
    """

    SETTINGS = HogQLGlobalSettings(
        max_execution_time=30,
        max_bytes_to_read=MAX_BYTES_TO_READ,
        read_overflow_mode="throw",
    )

    def __init__(
        self,
        *,
        team: Team,
        alert: LogsAlertConfiguration,
        date_from: dt.datetime,
        date_to: dt.datetime,
    ) -> None:
        if alert.team_id != team.id:
            raise ValueError(f"Alert {alert.id} belongs to team {alert.team_id}, not {team.id}")
        self.team = team
        self.alert = alert
        self.date_from = date_from
        self.date_to = date_to
        self.date_range = DateRange(date_from=date_from.isoformat(), date_to=date_to.isoformat())
        self.where_expr = build_alert_where_expr(team=team, alert=alert, date_from=date_from, date_to=date_to)

    def execute(self) -> AlertCheckCountResult:
        """Return a single aggregate count for the alert window."""
        self._tag()

        query = parse_select(
            """
            SELECT count() AS total
            FROM logs
            WHERE {where}
            """,
            placeholders={"where": self.where_expr},
        )

        start_ms = time.monotonic_ns() // 1_000_000
        response = self._run_query(query)
        duration_ms = time.monotonic_ns() // 1_000_000 - start_ms

        count = response.results[0][0] if response.results else 0
        return AlertCheckCountResult(count=count, query_duration_ms=duration_ms)

    def execute_bucketed(self, interval_minutes: int, *, limit: int = 10_000) -> list[BucketedCount]:
        """Return time-bucketed counts.

        Used by the simulate preview chart and (as of the stateless eval refactor)
        the production alert evaluator, which derives its N-of-M window directly
        from the bucket sequence. Operational contract callers depend on:

        - Buckets returned in ASC (oldest-first) order; alert eval reverses to get
          newest-first for the state machine.
        - `limit` bounds the row count to `evaluation_periods` for the eval path
          (preview path uses MAX_SIMULATE_BUCKETS).
        - Bucket boundaries are aligned to `toStartOfInterval(…, interval_minutes)`
          from midnight UTC — pass cadence-aligned `date_from`/`date_to` so each
          returned bucket holds a full `interval_minutes` of data.
        """
        self._tag()

        # Wrapping in toStartOfMinute() lets ClickHouse match the projection's
        # `time_bucket` key column and read pre-aggregated data instead of raw rows.
        time_field = (
            ast.Call(name="toStartOfMinute", args=[ast.Field(chain=["timestamp"])])
            if is_projection_eligible(self.alert.filters)
            else ast.Field(chain=["timestamp"])
        )
        query = parse_select(
            """
            SELECT
                toStartOfInterval({time_field}, toIntervalMinute({bucket_minutes})) AS bucket,
                count() AS total
            FROM logs
            WHERE {where}
            GROUP BY bucket
            ORDER BY bucket ASC
            LIMIT {row_limit}
            """,
            placeholders={
                "time_field": time_field,
                "bucket_minutes": ast.Constant(value=interval_minutes),
                "where": self.where_expr,
                "row_limit": ast.Constant(value=limit),
            },
        )

        response = self._run_query(query)
        return [BucketedCount(timestamp=row[0], count=row[1]) for row in response.results]

    def execute_periods(self, period_minutes: int, period_count: int) -> list[BucketedCount]:
        """Per-period counts anchored to `date_from`, oldest-first."""
        self._tag()
        ranges = _period_ranges(self.date_from, period_minutes, period_count)
        return self._execute_count_per_range(ranges)

    def execute_rolling_checks(
        self,
        nca: dt.datetime,
        window_minutes: int,
        cadence_minutes: int,
        period_count: int,
    ) -> list[BucketedCount]:
        """Per-check counts for M cadence-stepped rolling windows ending at NCA, oldest-first."""
        self._tag()
        ranges = _rolling_check_ranges(nca, window_minutes, cadence_minutes, period_count)
        return self._execute_count_per_range(ranges)

    def _execute_count_per_range(self, ranges: list[tuple[dt.datetime, dt.datetime]]) -> list[BucketedCount]:
        select_columns: list[ast.Expr] = [
            ast.Alias(
                alias=f"period_{i}",
                expr=ast.Call(name="countIf", args=[_timestamp_in_range(start, end)]),
            )
            for i, (start, end) in enumerate(ranges)
        ]

        query = ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=ast.Field(chain=["logs"])),
            where=self.where_expr,
        )
        response = self._run_query(query)
        row = response.results[0] if response.results else [0] * len(ranges)
        return [BucketedCount(timestamp=start, count=count) for (start, _), count in zip(ranges, row)]

    def _run_query(self, query: ast.SelectQuery | ast.SelectSetQuery) -> HogQLQueryResponse:
        if not isinstance(query, ast.SelectQuery):
            raise ValueError("Failed to build alert check query")

        return execute_hogql_query(
            query_type="alert_check",
            query=query,
            team=self.team,
            workload=Workload.LOGS,
            settings=self.SETTINGS,
            limit_context=LimitContext.QUERY,
            modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
        )

    def _tag(self) -> None:
        _tag_alert_query(team=self.team, alert_config_id=str(self.alert.id), source="logs_alert")


@dataclass(frozen=True)
class BatchedBucketedResult:
    """Per-alert bucketed counts plus the shared CH query duration of the batch."""

    per_alert: dict[str, list[BucketedCount]]
    query_duration_ms: int


class BatchedAlertCheckQuery:
    """Multi-alert batched alert check.

    Same shape as `AlertCheckQuery.execute_bucketed`, but evaluates N alerts in
    one CH query using `countIf(<filter>) AS alert_<n>` columns. All alerts must
    share team, time window, and bucket grid — caller groups by
    `(team_id, window_minutes, evaluation_periods, projection_eligible)`.

    The batched query reads each row once and evaluates all per-alert predicates
    as cheap column expressions, so cost is dominated by the (shared) partition
    scan, not by the predicate count. See
    [tmp/logs-alerting/per-team-batching-test.sql](../../../tmp/logs-alerting/per-team-batching-test.sql)
    for cost validation.

    The outer WHERE also carries the OR of all per-alert predicates, so rows
    matching no alert are pruned via the primary key and skip indexes before
    any countIf column is evaluated.
    """

    SETTINGS = AlertCheckQuery.SETTINGS

    def __init__(
        self,
        *,
        team: Team,
        alerts: list[LogsAlertConfiguration],
        date_from: dt.datetime,
        date_to: dt.datetime,
        projection_eligible: bool | None = None,
    ) -> None:
        if not alerts:
            raise ValueError("BatchedAlertCheckQuery requires at least one alert")
        if any(a.team_id != team.id for a in alerts):
            raise ValueError("All alerts in a batch must belong to the same team")
        self.team = team
        self.alerts = list(alerts)
        self.date_from = date_from
        self.date_to = date_to
        self._alert_where_exprs: list[ast.Expr] = [
            build_alert_where_expr(team=team, alert=alert, date_from=date_from, date_to=date_to)
            for alert in self.alerts
        ]
        # Caller (cohort orchestrator) already keys cohorts by projection eligibility,
        # so it can pass the answer through. Recompute only for direct/test callers.
        self._all_projection_eligible = (
            projection_eligible
            if projection_eligible is not None
            else all(is_projection_eligible(a.filters) for a in self.alerts)
        )

        # Outer WHERE owns the pruning so CH can skip parts/granules before
        # evaluating any countIf: the time bounds, plus the OR of every alert's
        # predicate. The disjunction is
        # result-equivalent because a row matching no alert's predicate
        # contributes to no countIf, but it lets CH prune with the primary key
        # (service_name) and the attributes bloom-filter skip indexes, which
        # cannot see predicates inside countIf. Per-alert exprs therefore appear
        # redundantly both here and inside their countIf, which is deliberate
        # and worth remembering when reading EXPLAIN output and counting
        # predicate evaluations.
        self._outer_where = parse_expr(
            "toStartOfDay(time_bucket) >= toStartOfDay({date_from})"
            " AND toStartOfDay(time_bucket) <= toStartOfDay({date_to})"
            " AND timestamp >= {date_from}"
            " AND timestamp < {date_to}",
            placeholders={
                "date_from": ast.Constant(value=date_from),
                "date_to": ast.Constant(value=date_to),
            },
        )
        # The hoisted copies must differ from the countIf copies in two ways.
        # They must be fresh instances, because the resolver annotates nodes
        # in place and sharing one instance at two positions in the query
        # tree is an aliasing hazard. And they must not carry indexHint(...)
        # wrappers: ClickHouse dedupes an expression that appears in both
        # the WHERE clause and a countIf argument, and when that shared
        # expression contains indexHint the filter step constant-folds one
        # use but not the other and the query fails with ILLEGAL_COLUMN
        # ("non constant in source stream but must be constant in result").
        # Dropping the hint loses nothing here: the real predicate sits in
        # the WHERE clause where the planner can use it directly.
        hoisted_exprs = [_strip_index_hints(e) for e in self._alert_where_exprs]
        hoisted = hoisted_exprs[0] if len(hoisted_exprs) == 1 else ast.Or(exprs=hoisted_exprs)
        self._outer_where = ast.And(exprs=[self._outer_where, hoisted])

    def execute_bucketed(self, interval_minutes: int, *, limit: int = 10_000) -> BatchedBucketedResult:
        """Run the batched query and split results back per-alert.

        All alerts in the batch must share `(window_minutes, evaluation_periods)`
        with the corresponding `interval_minutes` and `limit` — otherwise they
        produce different bucket grids and can't share a query.
        """
        self._tag()

        query = self._build_bucketed_query(interval_minutes, limit)

        start_ms = time.monotonic_ns() // 1_000_000
        response = self._run_query(query)
        duration_ms = time.monotonic_ns() // 1_000_000 - start_ms

        per_alert: dict[str, list[BucketedCount]] = {str(a.id): [] for a in self.alerts}
        for row in response.results:
            bucket_ts = row[0]
            for i, alert in enumerate(self.alerts):
                per_alert[str(alert.id)].append(BucketedCount(timestamp=bucket_ts, count=row[i + 1]))
        return BatchedBucketedResult(per_alert=per_alert, query_duration_ms=duration_ms)

    def execute_periods(self, period_minutes: int, period_count: int) -> BatchedBucketedResult:
        """Per-alert per-period counts anchored to `date_from`."""
        self._tag()
        ranges = _period_ranges(self.date_from, period_minutes, period_count)
        return self._execute_count_per_range(ranges)

    def execute_rolling_checks(
        self,
        nca: dt.datetime,
        window_minutes: int,
        cadence_minutes: int,
        period_count: int,
    ) -> BatchedBucketedResult:
        """Per-alert per-check counts for M cadence-stepped rolling windows ending at NCA."""
        self._tag()
        ranges = _rolling_check_ranges(nca, window_minutes, cadence_minutes, period_count)
        return self._execute_count_per_range(ranges)

    def _execute_count_per_range(self, ranges: list[tuple[dt.datetime, dt.datetime]]) -> BatchedBucketedResult:
        query = self._build_count_per_range_query(ranges)

        start_ms = time.monotonic_ns() // 1_000_000
        response = self._run_query(query)
        duration_ms = time.monotonic_ns() // 1_000_000 - start_ms

        # Cells are laid out alert-major: row[0..M-1] = alert 0's M periods,
        # row[M..2M-1] = alert 1's, etc. Empty result = all zeros.
        row = response.results[0] if response.results else [0] * (len(self.alerts) * len(ranges))
        per_alert: dict[str, list[BucketedCount]] = {}
        for alert_i, alert in enumerate(self.alerts):
            offset = alert_i * len(ranges)
            per_alert[str(alert.id)] = [
                BucketedCount(timestamp=start, count=row[offset + period_i])
                for period_i, (start, _) in enumerate(ranges)
            ]
        return BatchedBucketedResult(per_alert=per_alert, query_duration_ms=duration_ms)

    def _build_bucketed_query(self, interval_minutes: int, limit: int) -> ast.SelectQuery:
        time_field = (
            ast.Call(name="toStartOfMinute", args=[ast.Field(chain=["timestamp"])])
            if self._all_projection_eligible
            else ast.Field(chain=["timestamp"])
        )

        select_columns: list[ast.Expr] = [
            ast.Alias(
                alias="bucket",
                expr=ast.Call(
                    name="toStartOfInterval",
                    args=[time_field, ast.Call(name="toIntervalMinute", args=[ast.Constant(value=interval_minutes)])],
                ),
            ),
        ]
        for i, alert_expr in enumerate(self._alert_where_exprs):
            select_columns.append(
                ast.Alias(
                    alias=f"alert_{i}",
                    expr=ast.Call(name="countIf", args=[alert_expr]),
                )
            )

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=ast.Field(chain=["logs"])),
            where=self._outer_where,
            group_by=[ast.Field(chain=["bucket"])],
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["bucket"]), order="ASC")],
            limit=ast.Constant(value=limit),
        )

    def _build_count_per_range_query(self, ranges: list[tuple[dt.datetime, dt.datetime]]) -> ast.SelectQuery:
        select_columns: list[ast.Expr] = [
            ast.Alias(
                alias=f"alert_{alert_i}_period_{period_i}",
                expr=ast.Call(
                    name="countIf",
                    args=[ast.And(exprs=[alert_expr, _timestamp_in_range(start, end)])],
                ),
            )
            for alert_i, alert_expr in enumerate(self._alert_where_exprs)
            for period_i, (start, end) in enumerate(ranges)
        ]

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=ast.Field(chain=["logs"])),
            where=self._outer_where,
        )

    def _run_query(self, query: ast.SelectQuery) -> HogQLQueryResponse:
        return execute_hogql_query(
            query_type="alert_check",
            query=query,
            team=self.team,
            workload=Workload.LOGS,
            settings=self.SETTINGS,
            limit_context=LimitContext.QUERY,
            modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
        )

    def _tag(self) -> None:
        # `QueryTags` doesn't allow per-batch custom fields, so we tag the first
        # alert as the representative `alert_config_id`. Ops can identify a
        # batched query by `source` and read the full alert list from
        # `query_log.query` if needed.
        _tag_alert_query(
            team=self.team,
            alert_config_id=str(self.alerts[0].id),
            source="logs_alert_batched",
        )


# Fall back to `now` when the checkpoint is older than this — a quiet partition
# can pin `min(...)` hours behind while other partitions have fresh data.
CHECKPOINT_MAX_STALENESS = dt.timedelta(minutes=5)


def fetch_live_logs_checkpoint(team: Team) -> dt.datetime | None:
    tag_queries(
        product=Product.LOGS,
        feature=Feature.ALERTING,
        source="logs_alert",
        team_id=str(team.id),
    )
    response = execute_hogql_query(
        query_type="alert_check_checkpoint",
        query=LIVE_LOGS_CHECKPOINT_QUERY,
        team=team,
        workload=Workload.LOGS,
        modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
    )
    if not response.results or response.results[0][0] is None:
        return None
    checkpoint = response.results[0][0]
    if checkpoint.tzinfo is None:
        checkpoint = checkpoint.replace(tzinfo=ZoneInfo("UTC"))
    return checkpoint


def resolve_alert_date_to(nca: dt.datetime, checkpoint: dt.datetime | None) -> dt.datetime:
    """Anchor `date_to` on the alert's scheduled `next_check_at`, clamped to the
    ingestion checkpoint when the checkpoint is fresh enough.

    Anchoring on `next_check_at` (not wall-clock-now) is what makes the query
    window deterministic across retries and immune to scheduler lag — two evals
    of the same alert at different actual eval times produce the same `date_to`
    and thus the same query.
    """
    if checkpoint is None or (nca - checkpoint) > CHECKPOINT_MAX_STALENESS:
        return nca
    return min(nca, checkpoint)


def is_projection_eligible(filters: dict) -> bool:
    """True when filters use only serviceNames + severityLevels (no filterGroup values).

    The projection_aggregate_counts projection groups by (team_id, time_bucket,
    service_name, severity_text, resource_fingerprint), so it covers these two
    filter types. Any filterGroup values reference columns outside the projection
    and require a raw table scan.

    Returns False on malformed shapes so the caller falls through to the raw-scan
    path, where `PropertyGroupFilter.model_validate` surfaces a per-alert error
    instead of crashing discovery for every alert in the project.
    """
    filter_group = filters.get("filterGroup")
    if not filter_group:
        return True
    if not isinstance(filter_group, dict):
        return False
    for group in filter_group.get("values", []):
        if not isinstance(group, dict):
            return False
        if group.get("values"):
            return False
    return True
