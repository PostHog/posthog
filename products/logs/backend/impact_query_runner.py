from functools import cached_property
from typing import NamedTuple

from posthog.schema import CachedLogsQueryResponse, LogsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.logs.backend.group_by_query_runner import GroupByDimension, LogsGroupBySource
from products.logs.backend.logs_query_runner import (
    LogsQueryResponse,
    LogsQueryRunnerMixin,
    fail_fast_aggregate_settings,
)
from products.logs.backend.models import resolved_distinct_id_attribute_keys, resolved_session_id_attribute_keys

# Enough top values for a drill-down popover; the full distribution belongs to Group mode.
TOP_IDENTITY_VALUES = 5


class _IdentityCandidate(NamedTuple):
    field: str
    map_key: str
    dimension: GroupByDimension


def _identity_candidates(attribute_keys: list[str]) -> list[_IdentityCandidate]:
    # One candidate per (key, map), checking the log attributes before the resource
    # attributes for each key — the same precedence getSessionIdWithKey applies in
    # products/logs/frontend/utils.tsx, so the counts cover the logs the viewer renders
    # as links. attributes_map_str keys carry the ingestion MV's `__str` type suffix
    # (posthog/clickhouse/logs/logs34.py); resource_attributes is a plain map with
    # unsuffixed keys. The query reports a match by its position in this list, so the
    # order is a contract between the SQL and the response.
    candidates: list[_IdentityCandidate] = []
    for attribute_key in attribute_keys:
        candidates.append(
            _IdentityCandidate(
                field="attributes_map_str",
                map_key=f"{attribute_key}__str",
                dimension=GroupByDimension(key=attribute_key, source=LogsGroupBySource.LOG.value),
            )
        )
        candidates.append(
            _IdentityCandidate(
                field="resource_attributes",
                map_key=attribute_key,
                dimension=GroupByDimension(key=attribute_key, source=LogsGroupBySource.RESOURCE.value),
            )
        )
    return candidates


def _identity_read(candidate: _IdentityCandidate) -> ast.Expr:
    # Both maps are read with a bare arrayElement: the property-resolver route wraps map
    # reads in a has() guard that defeats the bucketed serialization and reads every key
    # bucket (see group_by_query_runner._dimension_expr). A missing key reads as '', which
    # nullIf scrubs to NULL so the aggregates can skip identity-less rows.
    read = ast.Call(
        name="arrayElement", args=[ast.Field(chain=[candidate.field]), ast.Constant(value=candidate.map_key)]
    )
    return ast.Call(name="nullIf", args=[read, ast.Constant(value="")])


def _identity_value_expr(candidates: list[_IdentityCandidate]) -> ast.Expr:
    # First non-empty value across the candidates.
    return ast.Call(name="coalesce", args=[_identity_read(candidate) for candidate in candidates])


def _identity_index_expr(candidates: list[_IdentityCandidate]) -> ast.Expr:
    # Position of the candidate the value expr matched, NULL when none matched. An integer
    # rather than the key itself, because naming the key in the row builds and hashes one
    # string per scanned row. The reads are the same expressions the value expr uses, so
    # ClickHouse evaluates each one once and the extra column adds nothing to the scan.
    args: list[ast.Expr] = []
    for index, candidate in enumerate(candidates):
        args.extend(
            [ast.Call(name="isNotNull", args=[_identity_read(candidate)]), ast.Constant(value=index)],
        )
    args.append(ast.Constant(value=None))
    return ast.Call(name="multiIf", args=args)


def _top_values(entries: list[tuple] | None) -> list[dict]:
    # topK(..., 'counts') rows are (value, count, error) tuples; the error margin is
    # noise for a popover, so only value and count survive.
    return [{"value": value, "count": int(count)} for value, count, _error in entries or []]


def _group_key(candidates: list[_IdentityCandidate], indexes: list[int] | None) -> dict | None:
    # The most frequent candidate position names the dimension that carries the counts.
    if not indexes:
        return None
    return candidates[indexes[0]].dimension._asdict()


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

    @cached_property
    def _session_candidates(self) -> list[_IdentityCandidate]:
        # The query and the response index into the same list, and resolved_* reads Postgres.
        return _identity_candidates(resolved_session_id_attribute_keys(self.team))

    @cached_property
    def _person_candidates(self) -> list[_IdentityCandidate]:
        return _identity_candidates(resolved_distinct_id_attribute_keys(self.team))

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
        (
            total,
            logs_with_session_id,
            sessions,
            logs_with_distinct_id,
            users,
            top_sessions,
            top_users,
            session_indexes,
            person_indexes,
        ) = response.results[0] if response.results else (0, 0, 0, 0, 0, [], [], [], [])
        return LogsQueryResponse(
            results={
                "total": total,
                "logsWithSessionId": logs_with_session_id,
                "sessions": sessions,
                "logsWithDistinctId": logs_with_distinct_id,
                "users": users,
                "topSessions": _top_values(top_sessions),
                "topUsers": _top_values(top_users),
                "sessionGroupKey": _group_key(self._session_candidates, session_indexes),
                "personGroupKey": _group_key(self._person_candidates, person_indexes),
            }
        )

    def to_query(self) -> ast.SelectQuery:
        # uniq() is HLL-based and ~1-2% off vs exact count(DISTINCT) on high-cardinality
        # ids, but much cheaper — the same tradeoff the error tracking aggregates accept.
        # topK is approximate in the same way. count(x)/uniq(x)/topK(x) skip NULLs, so rows
        # without an identity need no explicit predicate and stay out of the top lists.
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
                topK(1)(session_index) AS session_indexes,
                topK(1)(person_index) AS person_indexes
            FROM (
                SELECT
                    {session_value} AS session_value,
                    {person_value} AS person_value,
                    {session_index} AS session_index,
                    {person_index} AS person_index
                FROM logs
                WHERE {where}
            )
            """,
            placeholders={
                "session_value": _identity_value_expr(self._session_candidates),
                "person_value": _identity_value_expr(self._person_candidates),
                "session_index": _identity_index_expr(self._session_candidates),
                "person_index": _identity_index_expr(self._person_candidates),
                "where": self.where_with_timestamp_bounds(),
                "top_n": ast.Constant(value=TOP_IDENTITY_VALUES),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query
