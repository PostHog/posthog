from functools import cached_property
from typing import TYPE_CHECKING

from posthog.schema import (
    CachedTraceSpansQueryResponse,
    DateRange,
    PropertyGroupFilter,
    TraceSpansQuery,
    TraceSpansQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, ExecutionMode

from products.tracing.backend.logic import TraceSpansQueryRunnerMixin
from products.tracing.backend.models import (
    resolved_tracing_distinct_id_attribute_keys,
    resolved_tracing_session_id_attribute_keys,
)
from products.tracing.backend.span_identity import identity_value_expr

if TYPE_CHECKING:
    from posthog.models import Team

# Enough top values for a drill-down popover; a fuller list belongs to a facet.
TOP_IDENTITY_VALUES = 5


def _top_values(entries: list[tuple] | None) -> list[dict]:
    # topK(..., 'counts') rows are (value, count, error) tuples; the error margin is noise
    # for a popover, so only value and count survive.
    return [{"value": value, "count": int(count)} for value, count, _error in entries or []]


class TraceSpansImpactQueryRunner(TraceSpansQueryRunnerMixin, AnalyticsQueryRunner[TraceSpansQueryResponse]):
    """Counts the unique sessions and people behind the spans matching the given filters.

    Its own scan rather than an addition to the count query: the count serves every
    tracing user on every filter change, while these aggregates decompress the two
    attribute-map columns over the whole window and only the impact strip needs them.
    """

    query: TraceSpansQuery
    cached_response: CachedTraceSpansQueryResponse

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        # The same fail-fast caps the count runner uses against this table. The strip is passive
        # decoration, so an over-wide window must fail rather than hold a ClickHouse thread the
        # list query needs.
        return HogQLGlobalSettings(
            max_execution_time=30,
            max_bytes_to_read=10_000_000_000,
            read_overflow_mode="throw",
        )

    @cached_property
    def _session_keys(self) -> list[str]:
        return resolved_tracing_session_id_attribute_keys(self.team)

    @cached_property
    def _person_keys(self) -> list[str]:
        return resolved_tracing_distinct_id_attribute_keys(self.team)

    def _calculate(self) -> TraceSpansQueryResponse:
        response = execute_hogql_query(
            query_type="TraceSpansQuery",
            query=self.to_query(),
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            filters=self.query_date_range.to_hogql_filters(),
            settings=self.settings,
        )
        (
            total,
            spans_with_session_id,
            sessions,
            spans_with_distinct_id,
            users,
            top_sessions,
            top_users,
        ) = response.results[0] if response.results else (0, 0, 0, 0, 0, [], [])
        return TraceSpansQueryResponse(
            results={
                "total": total,
                "spansWithSessionId": spans_with_session_id,
                "sessions": sessions,
                "spansWithDistinctId": spans_with_distinct_id,
                "users": users,
                "topSessions": _top_values(top_sessions),
                "topUsers": _top_values(top_users),
            }
        )

    def to_query(self) -> ast.SelectQuery:
        # where() bounds the window by time_bucket (day precision); the explicit half-open
        # timestamp bounds make the counts match the requested window exactly, as the count
        # runner does.
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
        # uniq() and topK() are HyperLogLog-based, so they are about 1-2% off against an exact
        # count(DISTINCT) on high-cardinality ids, and much cheaper. That is the tradeoff the
        # error tracking and logs impact aggregates already accept. count(x)/uniq(x)/topK(x)
        # skip NULLs, so spans that carry no identity need no predicate and stay out of the
        # top lists.
        query = parse_select(
            """
            SELECT
                count() AS total,
                count(session_value) AS spans_with_session_id,
                uniq(session_value) AS sessions,
                count(person_value) AS spans_with_distinct_id,
                uniq(person_value) AS users,
                topK({top_n}, 3, 'counts')(session_value) AS top_sessions,
                topK({top_n}, 3, 'counts')(person_value) AS top_users
            FROM (
                SELECT {session_value} AS session_value, {person_value} AS person_value
                FROM posthog.trace_spans
                WHERE {where}
            )
            """,
            placeholders={
                "session_value": identity_value_expr(self._session_keys),
                "person_value": identity_value_expr(self._person_keys),
                "where": where_with_timestamp,
                "top_n": ast.Constant(value=TOP_IDENTITY_VALUES),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query


def run_impact_query(
    *,
    team: "Team",
    date_range: DateRange,
    service_names: list[str] | None = None,
    status_codes: list[int] | None = None,
    filter_group: PropertyGroupFilter | None = None,
) -> TraceSpansQueryResponse | CachedTraceSpansQueryResponse:
    """Facade-friendly entry point for running a span impact query."""
    query = TraceSpansQuery(
        dateRange=date_range,
        serviceNames=service_names,
        statusCodes=status_codes,
        filterGroup=filter_group,
    )
    runner = TraceSpansImpactQueryRunner(query, team)
    response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
    assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)
    return response
