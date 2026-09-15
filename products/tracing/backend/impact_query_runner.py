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
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, ExecutionMode

from products.tracing.backend.logic import TraceSpansScalarQueryRunnerMixin, fail_fast_scalar_settings
from products.tracing.backend.models import TracingIdentityAttributeKeys, resolved_tracing_identity_attribute_keys
from products.tracing.backend.span_identity import identity_value_expr

if TYPE_CHECKING:
    from posthog.models import Team

TOP_IDENTITY_VALUES = 5


def _top_values(entries: list[tuple] | None) -> list[dict]:
    # topK(..., 'counts') rows are (value, count, error) tuples; the error margin is popover noise.
    return [{"value": value, "count": int(count)} for value, count, _error in entries or []]


class TraceSpansImpactQueryRunner(TraceSpansScalarQueryRunnerMixin, AnalyticsQueryRunner[TraceSpansQueryResponse]):
    """Counts the unique sessions and people behind the spans matching the given filters.

    Its own scan rather than an addition to the count query: the count serves every tracing
    user on every filter change, while these aggregates decompress the two attribute-map
    columns over the whole window and only the impact strip needs them.
    """

    query: TraceSpansQuery
    cached_response: CachedTraceSpansQueryResponse

    def __init__(self, query: TraceSpansQuery, *args, identity_keys: TracingIdentityAttributeKeys, **kwargs) -> None:
        super().__init__(query, *args, **kwargs)
        self._identity_keys = identity_keys

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        # Unlike the bare count, this decompresses the attribute maps over a mostly identical
        # window on every filter tweak, hence the uncompressed block cache.
        return fail_fast_scalar_settings(use_uncompressed_cache=True)

    def _calculate(self) -> TraceSpansQueryResponse:
        results = self.execute()
        (
            total,
            spans_with_session_id,
            sessions,
            spans_with_distinct_id,
            users,
            top_sessions,
            top_users,
        ) = results[0] if results else (0, 0, 0, 0, 0, [], [])
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
        # uniq()/topK() are HyperLogLog-based: ~1-2% off an exact count(DISTINCT), much cheaper,
        # and NULL-skipping, so spans carrying no identity need no predicate.
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
                "session_value": identity_value_expr(self._identity_keys.session),
                "person_value": identity_value_expr(self._identity_keys.distinct_id),
                "where": self.where_with_exact_timestamps(),
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
    runner = TraceSpansImpactQueryRunner(query, team, identity_keys=resolved_tracing_identity_attribute_keys(team))
    # Cached, unlike the count beside it: the strip re-mounts and reloads whenever the user
    # leaves the traces view or turns compare on.
    response = runner.run(ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
    assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)
    return response
