from collections.abc import Sequence
from typing import TYPE_CHECKING, NamedTuple
from zoneinfo import ZoneInfo

from posthog.schema import CachedLogsQueryResponse, LogsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
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

# Cap on combined group-by dimensions: each extra dimension multiplies group cardinality
# and widens the GROUP BY tuple, while the scan cost stays roughly flat.
MAX_GROUP_DIMENSIONS = 4

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


class GroupByDimension(NamedTuple):
    key: str
    source: str


# Whole-set totals as window aggregates over the grouped rows: computed in one unsorted
# pass, so the ORDER BY + LIMIT below can heap-select the top-N instead of fully sorting
# every group, and the outer select only consumes N rows instead of the whole group set.
_TOTALS_WINDOW = "count() OVER () AS group_count, sum(log_count) OVER () AS log_count_sum"


class LogsGroupByQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Aggregates matching logs into groups by one or more attributes (or top-level fields).

    Grouping accepts up to MAX_GROUP_DIMENSIONS ordered dimensions; a group is the
    combination of its per-dimension values (GROUP BY tuple). Log attributes and
    top-level columns group in a single scan over the main `logs` table: the attribute
    maps live on the row (`Map(LowCardinality(String), String)` with bloom-filter key
    indexes), so grouping needs no join. Resource attributes are constant per
    `resource_fingerprint` (the hash of the whole resource map, part of the sort key),
    so those dimensions instead aggregate by the fingerprint — never reading the wide
    `resource_attributes` map — and translate fingerprint → value through the exploded
    `log_attributes` rollup, one INNER JOIN per resource dimension, like
    LogFacetValuesQueryRunner's resource path. One query returns the top-N groups AND
    the total distinct-group/log counts, by nesting the GROUP BY in a subquery and
    collecting `groupArray(N)` + `count()` + `sum()` in the outer select — the same
    shape LogAttributesQueryRunner uses for its keys-only path.

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
        group_bys: Sequence[tuple[str, str]],
        order_groups_by: str = "log_count",
        group_limit: int = DEFAULT_GROUP_LIMIT,
        **kwargs,
    ):
        super().__init__(query, *args, **kwargs)
        if not 1 <= len(group_bys) <= MAX_GROUP_DIMENSIONS:
            raise ValueError(f"group_bys must contain between 1 and {MAX_GROUP_DIMENSIONS} dimensions")
        dimensions = [GroupByDimension(key=key, source=source) for key, source in group_bys]
        for dimension in dimensions:
            if not dimension.key:
                raise ValueError("every group-by dimension requires a key")
            if dimension.source not in GROUP_SOURCES:
                raise ValueError(f"group-by dimension source must be one of {GROUP_SOURCES}")
            if dimension.source == "column" and dimension.key not in GROUPABLE_COLUMNS:
                raise ValueError(f"a 'column' dimension's key must be one of {tuple(GROUPABLE_COLUMNS)}")
        if len(set(dimensions)) != len(dimensions):
            raise ValueError("group_bys must not contain duplicate dimensions")
        if order_groups_by not in ORDER_FIELDS:
            raise ValueError(f"order_groups_by must be one of {ORDER_FIELDS}")
        self.group_bys = dimensions
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
            # Group-by is interactive: users re-query the same window while switching the
            # grouping key or ordering, re-decompressing the same attribute-map blocks each
            # time — over half the query cost. Let those scans use the server's uncompressed
            # block cache (a no-op where the cache is unsized). Guards sized to the runner's
            # own read cap so an over-budget scan can't pump more than MAX_READ_BYTES into it.
            use_uncompressed_cache=True,
            merge_tree_max_rows_to_use_cache=50_000_000,
            merge_tree_max_bytes_to_use_cache=MAX_READ_BYTES,
        )

    def _dimension_expr(self, dimension: GroupByDimension) -> ast.Expr:
        # Map keys are bound chain members / parsed from a fixed allowlist — the user-supplied
        # key can never be interpolated as SQL (same contract as column_expressions.path_to_expr).
        # Resource dimensions never come through here: they aggregate by resource_fingerprint
        # and translate to values via the log_attributes rollup join.
        if dimension.source == "log":
            # Log attributes are physically stored in type-suffixed maps (`attributes_map_str`).
            # Read the key with a bare arrayElement on the physical map: the property-resolver
            # route (`attributes.key__str`) wraps the read in a has() guard that defeats the
            # bucketed map serialization and reads every key bucket, ~5x the bytes. A missing
            # key yields '' here instead of NULL — both are excluded by the WHERE coalesce
            # filter, so group results are identical. An explicit Call (not ArrayAccess) keeps
            # the resolver from folding the subscript back into a property chain.
            return ast.Call(
                name="arrayElement",
                args=[ast.Field(chain=["attributes_map_str"]), ast.Constant(value=f"{dimension.key}__str")],
            )
        return parse_expr(GROUPABLE_COLUMNS[dimension.key])

    def to_query(self) -> ast.SelectQuery:
        # One generated alias (g0..gN) per dimension, in request order; the aliases are
        # module-generated strings, so interpolating them into the template is safe.
        aliases = [f"g{i}" for i in range(len(self.group_bys))]
        scan_dims = [(a, d) for a, d in zip(aliases, self.group_bys) if d.source != "resource"]
        resource_dims = [(a, d) for a, d in zip(aliases, self.group_bys) if d.source == "resource"]

        placeholders: dict[str, ast.Expr] = {"order_field": ast.Field(chain=[self.order_groups_by])}

        # Scan over `logs`: group by the non-resource dimension expressions plus (when any
        # resource dimension exists) the fingerprint. Rows without a non-resource dimension's
        # attribute are not a group: a missing map key reads as NULL (property-group scrub) or
        # '' (native subscript), and HogQL's `!=` lets NULL through, so both are excluded via
        # coalesce. Fresh AST nodes per placeholder — resolution annotates nodes in place.
        where_exprs = self._base_where()
        scan_cols = []
        for alias, dimension in scan_dims:
            placeholders[f"expr_{alias}"] = self._dimension_expr(dimension)
            where_exprs.append(
                parse_expr("coalesce({expr}, '') != ''", placeholders={"expr": self._dimension_expr(dimension)})
            )
            scan_cols.append(f"{{expr_{alias}}} AS {alias}")
        placeholders["where"] = ast.And(exprs=where_exprs)
        if resource_dims:
            scan_cols.append("resource_fingerprint")
        scan_group_cols = [alias for alias, _ in scan_dims] + (["resource_fingerprint"] if resource_dims else [])
        scan_sql = f"""
            SELECT
                {", ".join(scan_cols)},
                count() AS log_count,
                countIf(lower(severity_text) IN ('error', 'fatal')) AS error_count,
                max(timestamp) AS last_seen
            FROM logs
            WHERE {{where}}
            GROUP BY {", ".join(scan_group_cols)}
        """

        if resource_dims:
            # Resource attributes are fixed per resource_fingerprint (the fingerprint IS the
            # hash of the whole map), so the scan aggregates by the sort-key UInt64 alone and
            # each resource dimension's fingerprint → value translation comes from the
            # log_attributes rollup — the wide resource_attributes map is never read. The
            # INNER JOIN doubles as that dimension's "has this attribute, non-empty" filter:
            # fingerprints without the key (or with '' as the value) have no mapping row, so
            # their logs drop out of groups and totals alike.
            join_sql_parts = []
            for alias, dimension in resource_dims:
                placeholders[f"attribute_key_{alias}"] = ast.Constant(value=dimension.key)
                # Pruning only: the mapping is time-invariant, but bounding time_bucket keeps
                # the rollup read to the parts covering the window. The rollup's time_bucket is
                # toStartOfInterval(timestamp, 10min), so a log with timestamp >= date_from can
                # only land in a bucket >= toStartOfInterval(date_from, 10min) — the tightest
                # lower bound that still covers every in-window row (matches LogFacetValues).
                placeholders[f"date_from_{alias}"] = ast.Constant(value=self.query_date_range.date_from())
                placeholders[f"date_to_{alias}"] = ast.Constant(value=self.query_date_range.date_to())
                join_sql_parts.append(f"""
                    INNER JOIN (
                        SELECT
                            resource_fingerprint,
                            any(attribute_value) AS group_value
                        FROM log_attributes
                        WHERE attribute_type = 'resource'
                            AND attribute_key = {{attribute_key_{alias}}}
                            AND attribute_value != ''
                            AND time_bucket >= toStartOfInterval({{date_from_{alias}}}, toIntervalMinute(10))
                            AND time_bucket <= {{date_to_{alias}}}
                        GROUP BY resource_fingerprint
                    ) AS mapping_{alias}
                    ON agg.resource_fingerprint = mapping_{alias}.resource_fingerprint
                """)
            grouped_cols = [f"agg.{alias} AS {alias}" for alias, _ in scan_dims] + [
                f"mapping_{alias}.group_value AS {alias}" for alias, _ in resource_dims
            ]
            grouped_sql = f"""
                SELECT
                    {", ".join(grouped_cols)},
                    sum(agg.log_count) AS log_count,
                    sum(agg.error_count) AS error_count,
                    max(agg.last_seen) AS last_seen
                FROM ({scan_sql}) AS agg
                {" ".join(join_sql_parts)}
                GROUP BY {", ".join(aliases)}
            """
        else:
            grouped_sql = scan_sql

        # nosemgrep: hogql-fstring-audit - only interpolates the int self.group_limit, the module-level _TOTALS_WINDOW constant, and generated g0..gN aliases (no user input); grouping keys and date bounds flow in as ast placeholders
        query = parse_select(
            f"""
            SELECT
                groupArray({self.group_limit})((tuple({", ".join(aliases)}), log_count, error_count, last_seen)) AS groups,
                coalesce(any(group_count), 0) AS total_groups,
                coalesce(any(log_count_sum), 0) AS total_logs
            FROM (
                SELECT
                    {", ".join(aliases)}, log_count, error_count, last_seen,
                    {_TOTALS_WINDOW}
                FROM ({grouped_sql})
                ORDER BY {{order_field}} DESC, {", ".join(f"{alias} ASC" for alias in aliases)}
                LIMIT {self.group_limit}
            )
            """,
            placeholders=placeholders,
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _base_where(self) -> list[ast.Expr]:
        # LogsFilterBuilder.where() filters at day-precision via time_bucket; add explicit
        # per-row timestamp bounds (half-open) so group counts match the requested window.
        return [
            self.where(),
            parse_expr(
                "timestamp >= {date_from} AND timestamp < {date_to}",
                placeholders={
                    "date_from": ast.Constant(value=self.query_date_range.date_from()),
                    "date_to": ast.Constant(value=self.query_date_range.date_to()),
                },
            ),
        ]

    def _calculate(self) -> LogsQueryResponse:
        # The group-by templates only reference posthog-native tables (logs, log_attributes)
        # and the grouping key is a bound constant, so hand the executor a plain posthog-only
        # Database up front. Without it, the `{filters}` placeholder LogsFilterBuilder.where()
        # always emits makes the executor run the full per-query database build — warehouse
        # tables, saved queries, endpoints: several Postgres round trips this query never uses.
        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
            database=Database(timezone=self.team.timezone, week_start_day=self.team.week_start_day),
        )
        response = execute_hogql_query(
            query_type="LogsQuery",
            query=self.to_query(),
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            settings=self.settings,
            context=context,
        )

        groups_raw, total_groups, total_logs = response.results[0] if response.results else ([], 0, 0)
        groups = [
            {
                # `value` mirrors the first dimension for single-dimension callers; `values`
                # carries every dimension's value in request order.
                "value": values[0],
                "values": list(values),
                "log_count": int(log_count),
                "error_count": int(error_count),
                "last_seen": last_seen.replace(tzinfo=ZoneInfo("UTC")).isoformat(),
            }
            for values, log_count, error_count, last_seen in groups_raw
        ]
        return LogsQueryResponse(
            results={
                "groups": groups,
                "total_groups": int(total_groups),
                "total_logs": int(total_logs),
                "truncated": int(total_groups) > len(groups),
            }
        )
