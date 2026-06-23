from functools import cached_property

from posthog.schema import CachedLogsQueryResponse, LogsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.logs.backend.logs_query_runner import (
    LogsFilterBuilder,
    LogsQueryResponse,
    LogsQueryRunnerMixin,
    ilike_pattern,
)

# Columns a facet may group by. Each value is also the WHERE clause that gets omitted, so a facet's
# counts reflect every *other* active filter rather than its own selection.
FACET_FIELDS: frozenset[str] = frozenset({"severity_text", "service_name"})

DEFAULT_FACET_LIMIT = 100


class LogFacetValuesQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Per-value counts for a single facet field, cross-filtered.

    Every active filter is applied except the one belonging to `facet_field`, so selecting a value
    in a facet re-scopes the *other* facets without zeroing out the facet's own siblings — the
    standard faceted-search behaviour.
    """

    query: LogsQuery
    cached_response: CachedLogsQueryResponse

    def __init__(self, query: LogsQuery, facet_field: str, *args, facet_search: str | None = None, **kwargs):
        super().__init__(query, *args, **kwargs)
        if facet_field not in FACET_FIELDS:
            raise ValueError(f"Unsupported facet field: {facet_field!r}")
        self.facet_field = facet_field
        # Type-ahead over the facet's *own* values (e.g. service name contains "kafka"), distinct from
        # query.searchTerm which searches log bodies. Lets a dynamic facet search past the LIMIT window.
        self.facet_search = (facet_search or "").strip() or None

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        # Fail fast rather than scan unbounded data, matching CountQueryRunner.
        return HogQLGlobalSettings(
            max_execution_time=30,
            max_bytes_to_read=10_000_000_000,
            read_overflow_mode="throw",
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
        results = [{"value": row[0], "count": row[1]} for row in (response.results or [])]
        return LogsQueryResponse(results=results)

    def to_query(self) -> ast.SelectQuery:
        # The day-precision time_bucket prune in where() is widened to exact timestamp bounds so the
        # counts match the requested window (same half-open pattern as CountQueryRunner).
        exprs = [
            LogsFilterBuilder(
                self.query, self.team, self.query_date_range, exclude_facet_field=self.facet_field
            ).where(),
            parse_expr(
                "timestamp >= {date_from} AND timestamp < {date_to}",
                placeholders={
                    "date_from": ast.Constant(value=self.query_date_range.date_from()),
                    "date_to": ast.Constant(value=self.query_date_range.date_to()),
                },
            ),
        ]
        if self.facet_search:
            exprs.append(
                parse_expr(
                    "{facet_field} ILIKE {pattern}",
                    placeholders={
                        "facet_field": ast.Field(chain=[self.facet_field]),
                        # Escape %, _ and \ so user input matches literally instead of as wildcards.
                        "pattern": ast.Constant(value=ilike_pattern(self.facet_search)),
                    },
                )
            )
        where = ast.And(exprs=exprs)
        query = parse_select(
            """
            SELECT {facet_field} AS value, count() AS count
            FROM logs
            WHERE {where}
            GROUP BY {facet_field}
            ORDER BY count() DESC, {facet_field} ASC
            LIMIT {limit}
            """,
            placeholders={
                "facet_field": ast.Field(chain=[self.facet_field]),
                "where": where,
                "limit": ast.Constant(value=self.query.limit or DEFAULT_FACET_LIMIT),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query
