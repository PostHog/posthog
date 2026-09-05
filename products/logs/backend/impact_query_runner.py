from functools import cached_property

from posthog.schema import CachedLogsQueryResponse, LogsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.logs.backend.logs_query_runner import (
    LogsQueryResponse,
    LogsQueryRunnerMixin,
    fail_fast_aggregate_settings,
)
from products.logs.backend.models import resolved_distinct_id_attribute_keys, resolved_session_id_attribute_keys

# How many top sessions and top users the response carries. Enough for a drill-down
# popover; the full distribution belongs to Group mode.
TOP_IDENTITY_VALUES = 5


def _identity_value_expr(attribute_keys: list[str]) -> ast.Expr:
    # First non-empty value across the candidate keys, checking the log attributes before
    # the resource attributes for each key — the same precedence getSessionIdWithKey applies
    # in products/logs/frontend/utils.tsx, so the counts cover the logs the viewer renders
    # as links. Both maps are read with a bare arrayElement: the property-resolver route
    # wraps map reads in a has() guard that defeats the bucketed serialization and reads
    # every key bucket (see group_by_query_runner._dimension_expr). attributes_map_str keys
    # carry the ingestion MV's `__str` type suffix (posthog/clickhouse/logs/logs34.py);
    # resource_attributes is a plain map with unsuffixed keys. A missing key reads as '',
    # which nullIf scrubs to NULL so the aggregates can skip identity-less rows.
    args: list[ast.Expr] = []
    for attribute_key in attribute_keys:
        for field, key in (("attributes_map_str", f"{attribute_key}__str"), ("resource_attributes", attribute_key)):
            read = ast.Call(name="arrayElement", args=[ast.Field(chain=[field]), ast.Constant(value=key)])
            args.append(ast.Call(name="nullIf", args=[read, ast.Constant(value="")]))
    return ast.Call(name="coalesce", args=args)


def _identity_key_expr(attribute_keys: list[str]) -> ast.Expr:
    # Tag of the key the value expr matched ("log:<key>" or "resource:<key>"), NULL when none
    # matched. Same key order, same suffixed reads, and same precedence as
    # _identity_value_expr, so the most frequent tag names the (source, key) dimension that
    # reproduces the counts in the group-by endpoint's vocabulary. It reads the same map
    # entries as the value expr, so the extra expression adds no columns to the scan.
    args: list[ast.Expr] = []
    for attribute_key in attribute_keys:
        for field, key, tag in (
            ("attributes_map_str", f"{attribute_key}__str", f"log:{attribute_key}"),
            ("resource_attributes", attribute_key, f"resource:{attribute_key}"),
        ):
            read = ast.Call(name="arrayElement", args=[ast.Field(chain=[field]), ast.Constant(value=key)])
            matched = ast.Call(name="isNotNull", args=[ast.Call(name="nullIf", args=[read, ast.Constant(value="")])])
            args.append(ast.Call(name="if", args=[matched, ast.Constant(value=tag), ast.Constant(value=None)]))
    return ast.Call(name="coalesce", args=args)


def _top_values(entries: list[tuple] | None) -> list[dict]:
    # topK(..., 'counts') rows are (value, count, error) tuples; the error margin is
    # noise for a popover, so only value and count survive.
    return [{"value": value, "count": int(count)} for value, count, _error in entries or []]


class ImpactQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Counts the unique sessions and users behind the log entries matching the given filters.

    Kept as its own scan instead of folding into the sparkline query: the sparkline
    aggregates over toStartOfMinute(timestamp) so ClickHouse serves it from the
    minute-aggregate projection, and that projection does not carry the attribute maps
    the identity expressions read. A fold would push every sparkline onto a full scan,
    also for teams that have the impact strip flag off.
    """

    query: LogsQuery
    cached_response: CachedLogsQueryResponse

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        # Fail-fast caps like CountQueryRunner, plus the uncompressed block cache: unlike a
        # bare count, this query decompresses the two attribute-map columns over the whole
        # window and re-runs against a mostly identical window on every filter tweak.
        return fail_fast_aggregate_settings(use_uncompressed_cache=True)

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
        row = response.results[0] if response.results else (0, 0, 0, 0, 0, [], [], [])
        session_group_key = None
        if row[7]:
            # The dominant tag is "source:key"; keys can contain dots but never a colon
            # before the source prefix, so the first colon is the split point.
            source, _, key = row[7][0][0].partition(":")
            session_group_key = {"source": source, "key": key}
        return LogsQueryResponse(
            results={
                "total": row[0],
                "logsWithSessionId": row[1],
                "sessions": row[2],
                "logsWithDistinctId": row[3],
                "users": row[4],
                "topSessions": _top_values(row[5]),
                "topUsers": _top_values(row[6]),
                "sessionGroupKey": session_group_key,
            }
        )

    def to_query(self) -> ast.SelectQuery:
        # uniq() is HLL-based and ~1-2% off vs exact count(DISTINCT) on high-cardinality
        # ids, but much cheaper — the same tradeoff the error tracking aggregates accept.
        # topK is approximate in the same way. count(x)/uniq(x)/topK(x) skip NULLs, so rows
        # without an identity need no explicit predicate and stay out of the top lists.
        session_id_keys = resolved_session_id_attribute_keys(self.team)
        query = parse_select(
            """
            SELECT
                count() AS total,
                count(session_value) AS logs_with_session_id,
                uniq(session_value) AS sessions,
                count(person_value) AS logs_with_distinct_id,
                uniq(person_value) AS users,
                topK({top_n}, 3, 'counts')(session_value) AS top_sessions,
                topK({top_n}, 3, 'counts')(person_value) AS top_users,
                topK(1, 3, 'counts')(session_key) AS session_keys
            FROM (
                SELECT
                    {session_value} AS session_value,
                    {person_value} AS person_value,
                    {session_key} AS session_key
                FROM logs
                WHERE {where}
            )
            """,
            placeholders={
                "session_value": _identity_value_expr(session_id_keys),
                "person_value": _identity_value_expr(resolved_distinct_id_attribute_keys(self.team)),
                "session_key": _identity_key_expr(session_id_keys),
                "where": self.where_with_timestamp_bounds(),
                "top_n": ast.Constant(value=TOP_IDENTITY_VALUES),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query
