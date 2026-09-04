from functools import cached_property

from posthog.schema import CachedLogsQueryResponse, LogsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.logs.backend.logs_query_runner import LogsQueryResponse, LogsQueryRunnerMixin
from products.logs.backend.models import (
    DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEYS,
    DEFAULT_LOGS_SESSION_ID_ATTRIBUTE_KEYS,
    DISTINCT_ID_ATTRIBUTE_KEY_CONVENTIONS,
    SESSION_ID_ATTRIBUTE_KEY_CONVENTIONS,
    TeamLogsConfig,
)


def _identity_value_expr(attribute_keys: list[str]) -> ast.Expr:
    # First non-empty value across the candidate keys, checking the log attributes before
    # the resource attributes for each key — the same precedence getSessionIdWithKey applies
    # in products/logs/frontend/utils.tsx, so the counts cover exactly the logs the viewer
    # renders as links. attributes_map_str is read directly because session and distinct IDs
    # are strings, and a bare arrayElement on it touches one serialization bucket instead of
    # the whole typed-map family (see the field's comment in
    # posthog/hogql/database/schema/logs.py).
    args: list[ast.Expr] = []
    for attribute_key in attribute_keys:
        key = ast.Constant(value=attribute_key)
        args.append(parse_expr("nullIf(attributes_map_str[{key}], '')", placeholders={"key": key}))
        args.append(parse_expr("nullIf(resource_attributes[{key}], '')", placeholders={"key": key}))
    args.append(ast.Constant(value=""))
    return ast.Call(name="coalesce", args=args)


class ImpactQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Counts the unique sessions and users behind the log entries matching the given filters."""

    query: LogsQuery
    cached_response: CachedLogsQueryResponse

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        # Same fail-fast caps as CountQueryRunner: a headline aggregate should never
        # scan unbounded data.
        return HogQLGlobalSettings(
            max_execution_time=30,
            max_bytes_to_read=10_000_000_000,
            read_overflow_mode="throw",
        )

    @cached_property
    def _config(self) -> TeamLogsConfig | None:
        return TeamLogsConfig.objects.filter(team=self.team).first()

    def _session_id_keys(self) -> list[str]:
        configured = (
            self._config.logs_session_id_attribute_keys if self._config else None
        ) or DEFAULT_LOGS_SESSION_ID_ATTRIBUTE_KEYS
        # Also count the built-in convention keys the UI links regardless of team config,
        # mirroring _person_scope_expr. Deduped, configured keys first.
        return list(dict.fromkeys([*configured, *SESSION_ID_ATTRIBUTE_KEY_CONVENTIONS]))

    def _distinct_id_keys(self) -> list[str]:
        configured = (
            self._config.logs_distinct_id_attribute_keys if self._config else None
        ) or DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEYS
        return list(dict.fromkeys([*configured, *DISTINCT_ID_ATTRIBUTE_KEY_CONVENTIONS]))

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
        # LogsFilterBuilder.where() filters by toStartOfDay(time_bucket) which is
        # day-precision; adding explicit per-row timestamp bounds (half-open to avoid
        # double-counting on boundaries) makes the counts match the requested window.
        # Same pattern as CountQueryRunner.
        where_with_timestamp = ast.And(
            exprs=[
                self.where(),
                parse_expr(
                    "timestamp >= {date_from} AND timestamp < {date_to}",
                    placeholders={
                        "date_from": ast.Constant(value=self.query_date_range.date_from()),
                        "date_to": ast.Constant(value=self.query_date_range.date_to()),
                    },
                ),
            ]
        )
        # uniq() is HLL-based and ~1-2% off vs exact count(DISTINCT) on high-cardinality
        # ids, but much cheaper — the same tradeoff the error tracking aggregates accept.
        query = parse_select(
            """
            SELECT
                count() AS total,
                countIf(session_value != '') AS logs_with_session_id,
                uniqIf(session_value, session_value != '') AS sessions,
                countIf(person_value != '') AS logs_with_distinct_id,
                uniqIf(person_value, person_value != '') AS users
            FROM (
                SELECT {session_value} AS session_value, {person_value} AS person_value
                FROM logs
                WHERE {where}
            )
            """,
            placeholders={
                "session_value": _identity_value_expr(self._session_id_keys()),
                "person_value": _identity_value_expr(self._distinct_id_keys()),
                "where": where_with_timestamp,
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query
