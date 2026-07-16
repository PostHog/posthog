from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from posthog.schema import CachedLogsQueryResponse, LogsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models.filters.mixins.utils import cached_property

from products.logs.backend.logs_query_runner import LogsQueryResponse, LogsQueryRunnerMixin, severity_level_to_expr

if TYPE_CHECKING:
    from posthog.models import User

# Hard byte budgets with "throw": a grouped aggregation with partial input would report
# silently wrong counts, so an over-budget read must fail loudly (the UI asks the user
# to narrow the window) rather than return truncated aggregates. The rollup is orders of
# magnitude smaller than the logs table, so its budget is tighter — a rollup read that
# approaches it means something pathological, and it should fail fast.
MAX_READ_BYTES = 10_000_000_000
MAX_EXECUTION_TIME = 60
MAX_ROLLUP_READ_BYTES = 5_000_000_000
MAX_ROLLUP_EXECUTION_TIME = 30

DEFAULT_GROUP_LIMIT = 100
MAX_GROUP_LIMIT = 500

# Top-level log fields exposed as grouping keys (source="column"), mapped to the
# HogQL expression that yields their display value. trace_id/span_id are stored
# base64-encoded; hex is what users see in trace UIs.
GROUPABLE_COLUMNS: dict[str, str] = {
    "severity_level": "severity_text",
    "trace_id": "hex(tryBase64Decode(trace_id))",
    "span_id": "hex(tryBase64Decode(span_id))",
}

GROUP_SOURCES = ("log", "resource", "column")
ORDER_FIELDS = ("log_count", "error_count", "last_seen")


class LogsGroupByQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Aggregates matching logs into groups by one attribute (or top-level field).

    Two query paths, picked per request:

    - Rollup (`log_attributes`, the pre-aggregated attribute table): used whenever every
      active filter is expressible on it — date range (10-minute buckets), service names,
      severity (the rollup carries `severity_text` per row), resource fingerprint, and
      resource-attribute filters (fingerprint subquery, same as facet counts). Orders of
      magnitude cheaper than scanning `logs`, which keeps wide-window group-bys under the
      read budget at scale. Trade-off: `last_seen` degrades to 10-minute bucket precision,
      and attribute keys/values over 256 chars are absent (the rollup MV drops them).
    - Fallback scan over the main `logs` table: for `column` grouping and for filters the
      rollup has no dimension for (body search, log-attribute filters, non-severity log
      filters). The attribute maps live on the row, so grouping needs no join.

    Both paths return the top-N groups AND the total distinct-group/log counts in one
    query, by nesting the GROUP BY in a subquery and collecting `groupArray(N)` +
    `count()` + `sum()` in the outer select — the same shape LogAttributesQueryRunner
    uses for its keys-only path.

    The group-by parameters are runner constructor args, not query-model fields, so the
    runner must be invoked via `calculate()` (which the logs API does) — never through
    the caching `run()` path, where the cache key is derived from the query model alone.
    """

    query: LogsQuery
    cached_response: CachedLogsQueryResponse

    def __init__(
        self,
        query: LogsQuery,
        *args,
        group_by: str,
        group_by_source: str = "log",
        order_groups_by: str = "log_count",
        group_limit: int = DEFAULT_GROUP_LIMIT,
        **kwargs,
    ):
        super().__init__(query, *args, **kwargs)
        if not group_by:
            raise ValueError("group_by is required")
        if group_by_source not in GROUP_SOURCES:
            raise ValueError(f"group_by_source must be one of {GROUP_SOURCES}")
        if group_by_source == "column" and group_by not in GROUPABLE_COLUMNS:
            raise ValueError(f"group_by must be one of {tuple(GROUPABLE_COLUMNS)} when group_by_source is 'column'")
        if order_groups_by not in ORDER_FIELDS:
            raise ValueError(f"order_groups_by must be one of {ORDER_FIELDS}")
        self.group_by = group_by
        self.group_by_source = group_by_source
        self.order_groups_by = order_groups_by
        self.group_limit = max(1, min(group_limit, MAX_GROUP_LIMIT))

    def validate_query_runner_access(self, user: "User") -> bool:
        # Defensive: this runner is invoked directly via the logs API, never through the generic
        # /api/projects/:id/query/ endpoint. Mirror LogsQueryRunner and refuse user-initiated
        # generic-query access so it can't silently bypass that gate if ever registered.
        from posthog.rbac.user_access_control import UserAccessControlError

        raise UserAccessControlError("logs", "viewer")

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        return HogQLGlobalSettings(
            max_execution_time=MAX_ROLLUP_EXECUTION_TIME if self._use_rollup else MAX_EXECUTION_TIME,
            max_bytes_to_read=MAX_ROLLUP_READ_BYTES if self._use_rollup else MAX_READ_BYTES,
            read_overflow_mode="throw",
            timeout_overflow_mode="throw",
        )

    def _group_expr(self) -> ast.Expr:
        # Map keys are bound chain members / parsed from a fixed allowlist — the user-supplied
        # key can never be interpolated as SQL (same contract as column_expressions.path_to_expr).
        if self.group_by_source == "log":
            # Log attributes are physically stored in type-suffixed maps (`attributes_map_str`);
            # the `__str` suffix routes the read there via the property-group resolver, the same
            # way LogsFilterBuilder suffixes attribute filter keys. Reading the bare key would go
            # through the `attributes` ALIAS, which mapApply-rewrites every row's whole map.
            return ast.Field(chain=["attributes", f"{self.group_by}__str"])
        if self.group_by_source == "resource":
            return ast.Field(chain=["resource_attributes", self.group_by])
        return parse_expr(GROUPABLE_COLUMNS[self.group_by])

    def to_query(self) -> ast.SelectQuery:
        query = parse_select(
            """
            SELECT
                groupArray({limit})((group_value, log_count, error_count, last_seen)) AS groups,
                count() AS total_groups,
                sum(log_count) AS total_logs
            FROM {inner}
            """,
            placeholders={
                "limit": ast.Constant(value=self.group_limit),
                "inner": self._rollup_subquery() if self._use_rollup else self._logs_subquery(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    @cached_property
    def _use_rollup(self) -> bool:
        # The rollup can only serve the group-by when every active filter maps onto one of
        # its dimensions; anything it can't express (body search, log-attribute filters,
        # log filters other than severity_level, pagination cursors) forces the logs scan.
        if self.group_by_source == "column":
            return False
        if self.query.searchTerm or self.query.liveLogsCheckpoint or self.query.after:
            return False
        if self._filter_builder.attribute_filters:
            return False
        return all(f.key == "severity_level" for f in self._filter_builder.log_filters)

    def _logs_subquery(self) -> ast.SelectQuery:
        query = parse_select(
            """
            SELECT
                {group_expr} AS group_value,
                count() AS log_count,
                countIf(lower(severity_text) IN ('error', 'fatal')) AS error_count,
                max(timestamp) AS last_seen
            FROM logs
            WHERE {where}
            GROUP BY group_value
            ORDER BY {order_field} DESC, group_value ASC
            """,
            placeholders={
                # Fresh AST nodes per placeholder — resolution annotates nodes in place.
                "group_expr": self._group_expr(),
                "where": self._where(),
                "order_field": ast.Field(chain=[self.order_groups_by]),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _rollup_subquery(self) -> ast.SelectQuery:
        # attribute_count sums to the number of matching log rows, so the group counts and
        # totals line up with what the logs scan would return (modulo bucket-edge precision).
        query = parse_select(
            """
            SELECT
                attribute_value AS group_value,
                sum(attribute_count) AS log_count,
                sumIf(attribute_count, lower(severity_text) IN ('error', 'fatal')) AS error_count,
                max(time_bucket) AS last_seen
            FROM log_attributes
            WHERE {where}
            GROUP BY group_value
            ORDER BY {order_field} DESC, group_value ASC
            """,
            placeholders={
                "where": self._rollup_where(),
                "order_field": ast.Field(chain=[self.order_groups_by]),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _rollup_where(self) -> ast.Expr:
        context_exprs = self._filter_builder.rollup_context_exprs()
        exprs: list[ast.Expr] = [
            # Closed bounds on 10-minute bucket starts: every bucket overlapping the window is
            # included, so counts can include up to one bucket of out-of-window rows per edge.
            parse_expr(
                "time_bucket >= {date_from_start_of_interval} AND time_bucket <= {date_to_start_of_interval}",
                placeholders=self.attributes_query_date_range.to_placeholders(),
            ),
            parse_expr(
                # _use_rollup excludes the "column" source, so the remaining sources name
                # their rollup attribute_type directly.
                "attribute_type = {attribute_type} AND attribute_key = {attribute_key} AND attribute_value != ''",
                placeholders={
                    "attribute_type": ast.Constant(value=self.group_by_source),
                    "attribute_key": ast.Constant(value=self.group_by),
                },
            ),
            *context_exprs,
        ]
        if (severity_levels := self._filter_builder.severity_levels_expr()) is not None:
            exprs.append(severity_levels)
        # _use_rollup guarantees only severity_level filters remain in log_filters.
        for log_filter in self._filter_builder.log_filters:
            exprs.append(severity_level_to_expr(log_filter))
        if self._filter_builder.resource_attribute_filters or self._filter_builder.resource_attribute_negative_filters:
            # Only context filters may be pushed into the resource-fingerprint subquery: the
            # outer attribute_type/attribute_key constraint would contradict the subquery's
            # own attribute matching and empty it out.
            exprs.append(self.resource_filter(existing_filters=context_exprs))
        return ast.And(exprs=exprs)

    def _where(self) -> ast.Expr:
        # LogsFilterBuilder.where() filters at day-precision via time_bucket; add explicit
        # per-row timestamp bounds (half-open) so group counts match the requested window.
        # Rows without the grouping attribute are not a group: a missing map key reads as
        # NULL (property-group scrub) or '' (native subscript), and HogQL's `!=` lets NULL
        # through, so both must be excluded via coalesce.
        return ast.And(
            exprs=[
                self.where(),
                parse_expr(
                    "timestamp >= {date_from} AND timestamp < {date_to}",
                    placeholders={
                        "date_from": ast.Constant(value=self.query_date_range.date_from()),
                        "date_to": ast.Constant(value=self.query_date_range.date_to()),
                    },
                ),
                parse_expr("coalesce({group_expr}, '') != ''", placeholders={"group_expr": self._group_expr()}),
            ]
        )

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

        groups_raw, total_groups, total_logs = response.results[0] if response.results else ([], 0, 0)
        groups = [
            {
                "value": value,
                "log_count": int(log_count),
                "error_count": int(error_count),
                "last_seen": last_seen.replace(tzinfo=ZoneInfo("UTC")).isoformat(),
            }
            for value, log_count, error_count, last_seen in groups_raw
        ]
        return LogsQueryResponse(
            results={
                "groups": groups,
                "total_groups": int(total_groups),
                "total_logs": int(total_logs),
                "truncated": int(total_groups) > len(groups),
            }
        )
