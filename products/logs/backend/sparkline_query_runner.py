import datetime as dt
from functools import cached_property
from zoneinfo import ZoneInfo

from posthog.schema import LogsSparklineBreakdownBy, LogsSparklineRankBy

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.utils.breakdowns import BREAKDOWN_OTHER_STRING_LABEL
from posthog.models.team.logs_retention import DEFAULT_LOGS_RETENTION_DAYS

from products.logs.backend.logs_query_runner import COLUMN_FILTER_FACET_FIELDS, LogsQueryResponse, LogsQueryRunner
from products.logs.backend.services_query_runner import ROLLUP_BUCKET_SECONDS

# Maps API breakdown type to ClickHouse field name
BREAKDOWN_DB_FIELD: dict[LogsSparklineBreakdownBy, str] = {
    LogsSparklineBreakdownBy.SEVERITY: "severity_text",
    LogsSparklineBreakdownBy.SERVICE: "service_name",
}

DEFAULT_BREAKDOWN = LogsSparklineBreakdownBy.SEVERITY

# Column each rank metric orders breakdown values by. Ranking by bytes matters when the caller
# charts bytes: the top talkers by volume are not necessarily the top talkers by size.
RANK_BY_FIELD: dict[LogsSparklineRankBy, str] = {
    LogsSparklineRankBy.COUNT: "event_count",
    LogsSparklineRankBy.BYTES: "bytes_uncompressed",
}

DEFAULT_RANK_BY = LogsSparklineRankBy.COUNT

# How many breakdown values keep their own series before the tail is folded into one "other" row.
# Matches what the sparkline UI charts, so collapsing here discards nothing that would be drawn.
SPARKLINE_TOP_BREAKDOWN_VALUES = 10

# The volume preview must return quickly or fail clearly. Its bytes breakdown sums
# `_bytes_uncompressed`, which the minute-aggregate projection doesn't cover, so a
# high-volume service can fall back to a full table scan. Cap execution well below the
# 60s default so a slow preview surfaces an error promptly instead of appearing to hang.
SPARKLINE_PREVIEW_MAX_EXECUTION_SECONDS = 30


class SparklineQueryRunner(LogsQueryRunner):
    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        # Inherit LogsQueryRunner's distributed-logs settings — including the
        # allow_experimental_object_type / allow_experimental_join_condition / transform_null_in
        # bug-workaround flags it sets to False — and only tighten the execution timeout. Building
        # a fresh HogQLGlobalSettings here would silently re-enable those buggy defaults.
        return super().settings.model_copy(update={"max_execution_time": SPARKLINE_PREVIEW_MAX_EXECUTION_SECONDS})

    def _calculate(self) -> LogsQueryResponse:
        response = execute_hogql_query(
            query_type="LogsQuery",
            query=self.to_query(),
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            settings=self.settings,
        )

        result_key = (self.query.sparklineBreakdownBy or DEFAULT_BREAKDOWN).value  # 'severity' or 'service'

        results = []
        for result in response.results:
            breakdown_value = result[1] if result[1] not in (None, "") else "(no value)"
            row = {
                # Tag the bucket time as UTC so it serializes with an offset, matching the log
                # row timestamp and the live_logs_checkpoint the frontend compares it against.
                "time": result[0].replace(tzinfo=ZoneInfo("UTC")) if result[0] else result[0],
                result_key: breakdown_value,
                "count": result[2],
            }
            if self._ranks_by_bytes:
                # Other callers get no byte sum, and a zero would say that the logs have no bytes.
                row["bytes_uncompressed"] = result[3]
            results.append(row)

        return LogsQueryResponse(results=results)

    @property
    def _ranks_by_bytes(self) -> bool:
        return (self.query.sparklineRankBy or DEFAULT_RANK_BY) == LogsSparklineRankBy.BYTES

    @cached_property
    def _use_rollup(self) -> bool:
        # logs_volume_buckets holds only a log count for each 5-minute bucket, service and severity.
        date_range = self.query_date_range
        if date_range.interval_name != "minute" or (date_range.interval_count * 60) % ROLLUP_BUCKET_SECONDS != 0:
            return False
        if date_range.date_from() < self._rollup_cutoff:
            return False
        query = self.query
        if (
            self._ranks_by_bytes
            or query.searchTerm
            or query.resourceFingerprint
            or query.personId is not None
            or query.sessionId is not None
            or query.liveLogsCheckpoint
            or query.after
        ):
            return False
        filters = self._filter_builder
        if (
            filters.resource_attribute_filters
            or filters.resource_attribute_negative_filters
            or filters.attribute_filters
            or filters.attribute_filter_groups
        ):
            return False
        if not all(log_filter.key in COLUMN_FILTER_FACET_FIELDS for log_filter in filters.log_filters):
            return False
        # The rollup stores severity in lower case, and the logs table keeps the case of each log.
        severity_values: list[str] = []
        for log_filter in filters.log_filters:
            if log_filter.key == "severity_level" and log_filter.value is not None:
                values = log_filter.value if isinstance(log_filter.value, list) else [log_filter.value]
                severity_values.extend(str(value) for value in values)
        return all(value == value.lower() for value in severity_values)

    @cached_property
    def _rollup_cutoff(self) -> dt.datetime:
        # The rollup keeps a count longer than the logs table keeps the logs. No log gets a shorter
        # retention than the default, so no log after this time is expired.
        return dt.datetime.now(dt.UTC) - dt.timedelta(days=DEFAULT_LOGS_RETENTION_DAYS)

    def _logs_series_query(self) -> ast.SelectQuery:
        query = parse_select(
            """
                SELECT
                    toStartOfInterval({time_field}, {one_interval_period}) AS time,
                    {breakdown_field} AS breakdown_value,
                    count() AS event_count,
                    {bytes_uncompressed} AS bytes_uncompressed
                FROM logs
                WHERE {where} AND time >= {date_from_start_of_interval} AND time <= {date_to}
                GROUP BY breakdown_value, time
            """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                # The sparkline projection is aggregated over "toStartOfMinute(timestamp)"
                # so if we use `timestamp` we don't use the projection (even if we're calling toStartOfInterval on it)
                # explicitly use toStartOfMinute(timestamp) as the time field unless we're using a sub-minute interval
                "time_field": ast.Call(name="toStartOfMinute", args=[ast.Field(chain=["timestamp"])])
                if self.query_date_range.interval_name != "second"
                else ast.Field(chain=["timestamp"]),
                "where": self.where(),
                "breakdown_field": self._breakdown_field,
                # The minute-aggregate projection holds only count(). A byte sum in the query makes
                # ClickHouse read the raw rows, so only a caller that ranks by bytes gets one.
                "bytes_uncompressed": parse_expr("sum(_bytes_uncompressed)")
                if self._ranks_by_bytes
                else ast.Constant(value=0),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _rollup_series_query(self) -> ast.SelectQuery:
        exprs: list[ast.Expr] = [
            # The logs table query keeps each whole sparkline bucket that starts in the range.
            parse_expr(
                "time_bucket >= {date_from_start_of_interval}"
                " AND time_bucket < {date_to_start_of_interval} + {one_interval_period}",
                placeholders=self.query_date_range.to_placeholders(),
            ),
            # The first sparkline bucket can start before the range, and thus before the cutoff.
            parse_expr("time_bucket >= {cutoff}", placeholders={"cutoff": ast.Constant(value=self._rollup_cutoff)}),
            *self.column_filter_exprs(),
        ]
        if self.query.serviceNames:
            exprs.append(
                parse_expr(
                    "service_name IN {serviceNames}",
                    placeholders={
                        "serviceNames": ast.Tuple(exprs=[ast.Constant(value=str(sn)) for sn in self.query.serviceNames])
                    },
                )
            )
        if self.query.severityLevels:
            exprs.append(
                parse_expr(
                    "severity_text IN {severityLevels}",
                    placeholders={
                        "severityLevels": ast.Tuple(
                            exprs=[ast.Constant(value=str(sl)) for sl in self.query.severityLevels]
                        )
                    },
                )
            )
        query = parse_select(
            """
                SELECT
                    toStartOfInterval(time_bucket, {one_interval_period}) AS time,
                    {breakdown_field} AS breakdown_value,
                    sum(log_count) AS event_count,
                    0 AS bytes_uncompressed
                FROM posthog.logs_volume_buckets
                WHERE {where}
                GROUP BY breakdown_value, time
            """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                "where": ast.And(exprs=exprs),
                "breakdown_field": self._breakdown_field,
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    @property
    def _breakdown_field(self) -> ast.Field:
        return ast.Field(chain=[BREAKDOWN_DB_FIELD[self.query.sparklineBreakdownBy or DEFAULT_BREAKDOWN]])

    def to_query(self) -> ast.SelectQuery:
        # The row count is bounded by construction: the rollup in the joined subquery leaves at most
        # SPARKLINE_TOP_BREAKDOWN_VALUES + 1 breakdown values, and BUCKET_TARGET holds the spine near
        # 50 buckets, so ~550 rows is the ceiling for any range. The LIMIT below is a backstop.
        query = parse_select(
            """
                SELECT
                    am.time_bucket AS time,
                    ac.breakdown_value AS breakdown_value,
                    ifNull(ac.event_count, 0) AS count,
                    ifNull(ac.bytes_uncompressed, 0) AS bytes_uncompressed
                FROM (
                    SELECT
                        dateAdd({date_from_start_of_interval}, {number_interval_period}) AS time_bucket
                    FROM numbers(
                        floor(
                            dateDiff({interval},
                                     {date_from_start_of_interval},
                                     {date_to_start_of_interval}) / {interval_count} + 1
                                    )
                        )
                    WHERE
                        time_bucket >= {date_from_start_of_interval} and
                        time_bucket <= greatest(
                            {date_from_start_of_interval},
                            toStartOfInterval({date_to} - toIntervalSecond(1), {one_interval_period})
                        )
                ) AS am
                LEFT JOIN (
                    SELECT
                        time,
                        if(breakdown_rank <= {top_n}, breakdown_value, {other_label}) AS breakdown_value,
                        sum(event_count) AS event_count,
                        sum(bytes_uncompressed) AS bytes_uncompressed
                    FROM (
                        SELECT
                            time,
                            breakdown_value,
                            event_count,
                            bytes_uncompressed,
                            dense_rank() OVER (ORDER BY breakdown_total DESC, breakdown_value ASC)
                                AS breakdown_rank
                        FROM (
                            SELECT
                                time,
                                breakdown_value,
                                event_count,
                                bytes_uncompressed,
                                sum({rank_field}) OVER (PARTITION BY breakdown_value) AS breakdown_total
                            FROM {series}
                        )
                    )
                    GROUP BY time, breakdown_value
                ) AS ac ON am.time_bucket = ac.time
                ORDER BY time asc, breakdown_value asc
                LIMIT 1000
        """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                "series": self._rollup_series_query() if self._use_rollup else self._logs_series_query(),
                "rank_field": ast.Field(chain=[RANK_BY_FIELD[self.query.sparklineRankBy or DEFAULT_RANK_BY]]),
                "top_n": ast.Constant(value=SPARKLINE_TOP_BREAKDOWN_VALUES),
                "other_label": ast.Constant(value=BREAKDOWN_OTHER_STRING_LABEL),
            },
        )
        if not isinstance(query, ast.SelectQuery):
            raise Exception("NO!")
        return query
