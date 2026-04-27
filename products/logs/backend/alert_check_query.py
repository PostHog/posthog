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

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team

from products.logs.backend.logs_query_runner import LogsFilterBuilder
from products.logs.backend.models import LogsAlertConfiguration


@dataclass(frozen=True)
class AlertCheckCountResult:
    count: int
    query_duration_ms: int


@dataclass(frozen=True)
class BucketedCount:
    timestamp: dt.datetime
    count: int


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
        max_bytes_to_read=50_000_000_000,  # 50GB
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
        self.date_range = DateRange(date_from=date_from.isoformat(), date_to=date_to.isoformat())

        logs_query = self._build_logs_query()
        query_date_range = QueryDateRange(
            date_range=logs_query.dateRange,
            team=team,
            interval=IntervalType.MINUTE,
            interval_count=1,
            now=date_to,
            timezone_info=ZoneInfo("UTC"),
            exact_timerange=True,
        )
        builder = LogsFilterBuilder(logs_query, team, query_date_range)
        base_where = builder.where()

        # Add explicit timestamp bounds using a half-open interval [from, to).
        # This ensures adjacent alert windows don't double-count logs at the boundary.
        # LogsFilterBuilder.where() includes a {filters} placeholder that resolves
        # to `true` when no HogQLFilters are passed to execute_hogql_query.
        self.where_expr = ast.And(
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
        """Return time-bucketed counts for preview charts."""
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
        tag_queries(
            product=Product.LOGS,
            feature=Feature.ALERTING,
            source="logs_alert",
            alert_config_id=str(self.alert.id),
            team_id=str(self.team.id),
        )

    def _build_logs_query(self) -> LogsQuery:
        filters = self.alert.filters
        filter_group = filters.get("filterGroup")
        if filter_group:
            pg = PropertyGroupFilter.model_validate(filter_group)
        else:
            pg = PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[PropertyGroupFilterValue(type=FilterLogicalOperator.AND_, values=[])],
            )

        return LogsQuery(
            dateRange=self.date_range,
            serviceNames=filters.get("serviceNames", []),
            severityLevels=filters.get("severityLevels", []),
            filterGroup=pg,
            kind="LogsQuery",
        )


# Explicit per-partition `GROUP BY` is required on both the dev `MergeTree`
# shard (no auto-merge at all) and the prod `AggregatingMergeTree` between
# merges. A bare `min(max_observed_timestamp)` scans every raw insert and
# returns the oldest value ever written.
_LIVE_LOGS_CHECKPOINT_SQL = """
    SELECT min(partition_checkpoint) FROM (
        SELECT _topic, _partition, max(max_observed_timestamp) AS partition_checkpoint
        FROM logs_kafka_metrics
        GROUP BY _topic, _partition
    )
"""

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
        query=parse_select(_LIVE_LOGS_CHECKPOINT_SQL),
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


def resolve_alert_date_to(now: dt.datetime, checkpoint: dt.datetime | None) -> dt.datetime:
    """Anchor `date_to` on the checkpoint when fresh, else fall back to `now`."""
    if checkpoint is None or (now - checkpoint) > CHECKPOINT_MAX_STALENESS:
        return now
    return min(now, checkpoint)


def is_projection_eligible(filters: dict) -> bool:
    """True when filters use only serviceNames + severityLevels (no filterGroup values).

    The projection_aggregate_counts projection groups by (team_id, time_bucket,
    service_name, severity_text, resource_fingerprint), so it covers these two
    filter types. Any filterGroup values reference columns outside the projection
    and require a raw table scan.
    """
    filter_group = filters.get("filterGroup")
    if not filter_group:
        return True
    for group in filter_group.get("values", []):
        if group.get("values"):
            return False
    return True
