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


class ImpactQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Counts the unique sessions and users behind the log entries matching the given filters."""

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
        row = response.results[0] if response.results else (0, 0, 0, 0, 0)
        return LogsQueryResponse(
            results={
                "total": row[0],
                "logsWithSessionId": row[1],
                "sessions": row[2],
                "logsWithDistinctId": row[3],
                "users": row[4],
            }
        )

    def to_query(self) -> ast.SelectQuery:
        # uniq() is HLL-based and ~1-2% off vs exact count(DISTINCT) on high-cardinality
        # ids, but much cheaper — the same tradeoff the error tracking aggregates accept.
        # count(x)/uniq(x) skip NULLs, so rows without an identity need no explicit predicate.
        query = parse_select(
            """
            SELECT
                count() AS total,
                count(session_value) AS logs_with_session_id,
                uniq(session_value) AS sessions,
                count(person_value) AS logs_with_distinct_id,
                uniq(person_value) AS users
            FROM (
                SELECT {session_value} AS session_value, {person_value} AS person_value
                FROM logs
                WHERE {where}
            )
            """,
            placeholders={
                "session_value": _identity_value_expr(resolved_session_id_attribute_keys(self.team)),
                "person_value": _identity_value_expr(resolved_distinct_id_attribute_keys(self.team)),
                "where": self.where_with_timestamp_bounds(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query
