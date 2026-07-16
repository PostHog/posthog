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

from products.logs.backend.logs_query_runner import LogsQueryResponse, LogsQueryRunnerMixin

if TYPE_CHECKING:
    from posthog.models import User

# Hard byte budget with "throw": a grouped aggregation with partial input would report
# silently wrong counts, so an over-budget scan must fail loudly (the UI asks the user
# to narrow the window) rather than return truncated aggregates.
MAX_READ_BYTES = 10_000_000_000
MAX_EXECUTION_TIME = 60

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

    Single scan over the main `logs` table: the attribute maps live on the row
    (`Map(LowCardinality(String), String)` with bloom-filter key indexes), so grouping
    needs no join against the exploded `log_attributes` side table. One query returns
    the top-N groups AND the total distinct-group/log counts, by nesting the GROUP BY
    in a subquery and collecting `groupArray(N)` + `count()` + `sum()` in the outer
    select — the same shape LogAttributesQueryRunner uses for its keys-only path.

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
            max_execution_time=MAX_EXECUTION_TIME,
            max_bytes_to_read=MAX_READ_BYTES,
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
            FROM (
                SELECT
                    {group_expr} AS group_value,
                    count() AS log_count,
                    countIf(lower(severity_text) IN ('error', 'fatal')) AS error_count,
                    max(timestamp) AS last_seen
                FROM logs
                WHERE {where}
                GROUP BY group_value
                ORDER BY {order_field} DESC, group_value ASC
            )
            """,
            placeholders={
                "limit": ast.Constant(value=self.group_limit),
                # Fresh AST nodes per placeholder — resolution annotates nodes in place.
                "group_expr": self._group_expr(),
                "where": self._where(),
                "order_field": ast.Field(chain=[self.order_groups_by]),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

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
