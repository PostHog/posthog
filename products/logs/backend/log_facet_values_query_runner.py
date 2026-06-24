from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, cast

from posthog.schema import CachedLogsQueryResponse, LogsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.logs.backend.logs_query_runner import (
    LogsFilterBuilder,
    LogsQueryResponse,
    LogsQueryRunnerMixin,
    ilike_pattern,
)

if TYPE_CHECKING:
    from posthog.models import Team

# Columns a facet may group by. Each value is also the WHERE clause that gets omitted, so a facet's
# counts reflect every *other* active filter rather than its own selection.
FACET_FIELDS: frozenset[str] = frozenset({"severity_text", "service_name"})

DEFAULT_FACET_LIMIT = 100

# Upper bound on facets in a single batch request — keeps the UNION query (one branch per facet) bounded.
MAX_FACETS_PER_REQUEST = 50


@dataclass
class LogFacet:
    """A single facet target in a batch request, identified by a client-supplied key echoed back in the response."""

    key: str
    facet_field: str | None = None
    facet_resource_attribute: str | None = None
    facet_attribute: str | None = None
    facet_search: str | None = None

    def __post_init__(self) -> None:
        if sum(bool(f) for f in (self.facet_field, self.facet_resource_attribute, self.facet_attribute)) != 1:
            raise ValueError("Provide exactly one of facet_field, facet_resource_attribute, or facet_attribute")
        if self.facet_field is not None and self.facet_field not in FACET_FIELDS:
            raise ValueError(f"Unsupported facet field: {self.facet_field!r}")
        self.facet_search = (self.facet_search or "").strip() or None


def _facet_expr(facet_field: str | None, facet_resource_attribute: str | None, facet_attribute: str | None) -> ast.Expr:
    """The expression a facet groups by: a top-level column, a resource_attributes or attributes map lookup."""
    if facet_field is not None:
        return ast.Field(chain=[facet_field])
    if facet_resource_attribute is not None:
        return ast.Field(chain=["resource_attributes", facet_resource_attribute])
    return ast.Field(chain=["attributes", cast(str, facet_attribute)])


def build_facet_select(
    query: LogsQuery,
    team: "Team",
    query_date_range: QueryDateRange,
    *,
    facet_field: str | None = None,
    facet_resource_attribute: str | None = None,
    facet_attribute: str | None = None,
    facet_search: str | None = None,
    facet_key: str | None = None,
) -> ast.SelectQuery:
    """Cross-filtered per-value counts for one facet.

    Every active filter is applied except the one belonging to this facet (via the exclude_* args on
    LogsFilterBuilder), so selecting a value re-scopes the *other* facets without zeroing its siblings.
    When facet_key is set the select also emits it as a literal column and casts the value to String, so
    the result can be UNION ALL'd with other facets' selects into one batch query.
    """
    is_map_facet = facet_resource_attribute is not None or facet_attribute is not None
    facet = _facet_expr(facet_field, facet_resource_attribute, facet_attribute)
    # The day-precision time_bucket prune in where() is widened to exact timestamp bounds so the counts
    # match the requested window (same half-open pattern as CountQueryRunner).
    filter_builder = LogsFilterBuilder(
        query,
        team,
        query_date_range,
        exclude_facet_field=facet_field,
        exclude_resource_attribute=facet_resource_attribute,
        exclude_attribute=facet_attribute,
    )
    exprs: list[ast.Expr] = [
        filter_builder.where(),
        parse_expr(
            "timestamp >= {date_from} AND timestamp < {date_to}",
            placeholders={
                "date_from": ast.Constant(value=query_date_range.date_from()),
                "date_to": ast.Constant(value=query_date_range.date_to()),
            },
        ),
    ]
    if is_map_facet:
        # A missing map key reads back as '' in ClickHouse — exclude it so the facet doesn't show a
        # blank value counting every log that lacks the attribute.
        exprs.append(parse_expr("{facet} != ''", placeholders={"facet": facet}))
    search = (facet_search or "").strip() or None
    if search:
        exprs.append(
            parse_expr(
                "{facet} ILIKE {pattern}",
                # Escape %, _ and \ so user input matches literally instead of as wildcards.
                placeholders={"facet": facet, "pattern": ast.Constant(value=ilike_pattern(search))},
            )
        )
    where = ast.And(exprs=exprs)
    limit = ast.Constant(value=query.limit or DEFAULT_FACET_LIMIT)

    if facet_key is None:
        select = parse_select(
            """
            SELECT {facet} AS value, count() AS count
            FROM logs
            WHERE {where}
            GROUP BY {facet}
            ORDER BY count() DESC, {facet} ASC
            LIMIT {limit}
            """,
            placeholders={"facet": facet, "where": where, "limit": limit},
        )
    else:
        # toString keeps the value column's type identical across all facets so the per-facet selects
        # are UNION ALL compatible (severity_text is LowCardinality, map lookups are String).
        select = parse_select(
            """
            SELECT {facet_key} AS facet_key, toString({facet}) AS value, count() AS count
            FROM logs
            WHERE {where}
            GROUP BY {facet}
            ORDER BY count() DESC, {facet} ASC
            LIMIT {limit}
            """,
            placeholders={
                "facet_key": ast.Constant(value=facet_key),
                "facet": facet,
                "where": where,
                "limit": limit,
            },
        )
    assert isinstance(select, ast.SelectQuery)
    return select


def _facet_settings() -> HogQLGlobalSettings:
    # Fail fast rather than scan unbounded data, matching CountQueryRunner.
    return HogQLGlobalSettings(max_execution_time=30, max_bytes_to_read=10_000_000_000, read_overflow_mode="throw")


class LogFacetValuesQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Per-value counts for a single facet, cross-filtered.

    The facet is a top-level column (severity_text/service_name), a resource attribute map key
    (e.g. k8s.namespace.name), or a log attribute map key (e.g. http.status_code). Every active
    filter is applied except the one belonging to this facet, so selecting a value re-scopes the
    *other* facets without zeroing out its own siblings — the standard faceted-search behaviour.
    """

    query: LogsQuery
    cached_response: CachedLogsQueryResponse

    def __init__(
        self,
        query: LogsQuery,
        *args,
        facet_field: str | None = None,
        facet_resource_attribute: str | None = None,
        facet_attribute: str | None = None,
        facet_search: str | None = None,
        **kwargs,
    ):
        super().__init__(query, *args, **kwargs)
        self.facet = LogFacet(
            key="",
            facet_field=facet_field,
            facet_resource_attribute=facet_resource_attribute,
            facet_attribute=facet_attribute,
            facet_search=facet_search,
        )

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        return _facet_settings()

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
        return build_facet_select(
            self.query,
            self.team,
            self.query_date_range,
            facet_field=self.facet.facet_field,
            facet_resource_attribute=self.facet.facet_resource_attribute,
            facet_attribute=self.facet.facet_attribute,
            facet_search=self.facet.facet_search,
        )


class LogFacetValuesMultiQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Cross-filtered per-value counts for many facets in one query.

    Each facet's select is built exactly as the single-facet runner builds it (same own-filter
    exclusion), then they're UNION ALL'd into a single ClickHouse query so the rail fetches every
    facet in one request. Results are tagged with each facet's client-supplied key for bucketing.
    """

    query: LogsQuery
    cached_response: CachedLogsQueryResponse

    def __init__(self, query: LogsQuery, *args, facets: list[LogFacet], **kwargs):
        super().__init__(query, *args, **kwargs)
        if not facets:
            raise ValueError("Provide at least one facet")
        if len(facets) > MAX_FACETS_PER_REQUEST:
            raise ValueError(f"At most {MAX_FACETS_PER_REQUEST} facets per request")
        self.facets = facets

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        return _facet_settings()

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
        results = [{"facetKey": row[0], "value": row[1], "count": row[2]} for row in (response.results or [])]
        return LogsQueryResponse(results=results)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        selects: list[ast.SelectQuery | ast.SelectSetQuery] = [
            build_facet_select(
                self.query,
                self.team,
                self.query_date_range,
                facet_field=facet.facet_field,
                facet_resource_attribute=facet.facet_resource_attribute,
                facet_attribute=facet.facet_attribute,
                facet_search=facet.facet_search,
                facet_key=facet.key,
            )
            for facet in self.facets
        ]
        return ast.SelectSetQuery.create_from_queries(selects, "UNION ALL")
