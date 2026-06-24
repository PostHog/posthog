import datetime as dt
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

from posthog.schema import CachedLogsQueryResponse, IntervalType, LogsQuery

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

# Upper bound on facets in a single batch request — bounds the attribute query's OR list and the
# number of per-column logs queries.
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
) -> ast.SelectQuery:
    """Cross-filtered per-value counts for one facet over the `logs` table.

    Every active filter is applied except the one belonging to this facet (via the exclude_* args on
    LogsFilterBuilder), so selecting a value re-scopes the *other* facets without zeroing its siblings.
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
    select = parse_select(
        """
        SELECT {facet} AS value, count() AS count
        FROM logs
        WHERE {where}
        GROUP BY {facet}
        ORDER BY count() DESC, {facet} ASC
        LIMIT {limit}
        """,
        placeholders={
            "facet": facet,
            "where": ast.And(exprs=exprs),
            "limit": ast.Constant(value=query.limit or DEFAULT_FACET_LIMIT),
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
    """Per-value counts for many facets in one request.

    Attribute facets (resource + log attribute keys) are answered by a single SELECT against the
    pre-aggregated `log_attributes` table — one row per (attribute_type, attribute_key,
    attribute_value), with `LIMIT n BY` giving each facet its own top-N — scoped by time range and
    service. Column facets (severity_text/service_name) aren't in that table, so each runs as its own
    cross-filtered `logs` query. Results from all are tagged with each facet's client key.
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
        self.attribute_facets = [f for f in facets if f.facet_resource_attribute or f.facet_attribute]
        self.column_facets = [f for f in facets if f.facet_field]

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        # `log_attributes` is bucketed by time_bucket; mirror LogValuesQueryRunner's fixed 10-minute
        # interval so the time-bucket bounds line up with how the table is aggregated.
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=IntervalType.MINUTE,
            interval_count=10,
            now=dt.datetime.now(),
            timezone_info=ZoneInfo("UTC"),
        )

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        return _facet_settings()

    def _attribute_pairs(self) -> list[tuple[str, str, LogFacet]]:
        """(attribute_type, attribute_key, facet) for each attribute facet."""
        pairs: list[tuple[str, str, LogFacet]] = []
        for facet in self.attribute_facets:
            if facet.facet_resource_attribute is not None:
                pairs.append(("resource", facet.facet_resource_attribute, facet))
            else:
                pairs.append(("log", cast(str, facet.facet_attribute), facet))
        return pairs

    def _attribute_query(self) -> ast.SelectQuery:
        # One OR branch per facet so each can carry its own type-ahead search; LIMIT BY then takes the
        # top values per (type, key). Scoped by time bucket + service only — log_attributes carries
        # neither severity nor log body, so those filters can't apply here.
        facet_exprs: list[ast.Expr] = []
        for attribute_type, attribute_key, facet in self._attribute_pairs():
            conds: list[ast.Expr] = [
                parse_expr(
                    "attribute_type = {type} AND attribute_key = {key}",
                    placeholders={
                        "type": ast.Constant(value=attribute_type),
                        "key": ast.Constant(value=attribute_key),
                    },
                )
            ]
            if facet.facet_search:
                conds.append(
                    parse_expr(
                        "attribute_value ILIKE {pattern}",
                        placeholders={"pattern": ast.Constant(value=ilike_pattern(facet.facet_search))},
                    )
                )
            facet_exprs.append(ast.And(exprs=conds) if len(conds) > 1 else conds[0])

        where_exprs: list[ast.Expr] = [
            parse_expr(
                "time_bucket >= {date_from_start_of_interval} "
                "AND time_bucket <= {date_to_start_of_interval} + {one_interval_period}",
                placeholders=self.query_date_range.to_placeholders(),
            ),
            ast.Or(exprs=facet_exprs) if len(facet_exprs) > 1 else facet_exprs[0],
            parse_expr("attribute_value != ''"),
        ]
        if self.query.serviceNames:
            where_exprs.append(
                parse_expr(
                    "service_name IN {serviceNames}",
                    placeholders={
                        "serviceNames": ast.Tuple(exprs=[ast.Constant(value=str(sn)) for sn in self.query.serviceNames])
                    },
                )
            )

        select = parse_select(
            """
            SELECT attribute_type, attribute_key, attribute_value AS value, sum(attribute_count) AS count
            FROM log_attributes
            WHERE {where}
            GROUP BY attribute_type, attribute_key, attribute_value
            ORDER BY attribute_key ASC, count DESC, value ASC
            LIMIT {limit} BY (attribute_type, attribute_key)
            """,
            placeholders={
                "where": ast.And(exprs=where_exprs),
                "limit": ast.Constant(value=self.query.limit or DEFAULT_FACET_LIMIT),
            },
        )
        assert isinstance(select, ast.SelectQuery)
        return select

    def _column_query(self, facet: LogFacet) -> ast.SelectQuery:
        return build_facet_select(
            self.query,
            self.team,
            self.query_date_range,
            facet_field=facet.facet_field,
            facet_search=facet.facet_search,
        )

    def to_query(self) -> ast.SelectQuery:
        # The framework expects a single representative query; the real work spans several in _calculate.
        if self.attribute_facets:
            return self._attribute_query()
        return self._column_query(self.column_facets[0])

    def _run(self, query: ast.SelectQuery) -> list:
        response = execute_hogql_query(
            query_type="LogsQuery",
            query=query,
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            settings=self.settings,
        )
        return response.results or []

    def _calculate(self) -> LogsQueryResponse:
        results: list[dict] = []
        if self.attribute_facets:
            key_by_pair = {(t, k): facet.key for t, k, facet in self._attribute_pairs()}
            for attribute_type, attribute_key, value, count in self._run(self._attribute_query()):
                facet_key = key_by_pair.get((attribute_type, attribute_key))
                if facet_key is not None:
                    results.append({"facetKey": facet_key, "value": value, "count": count})
        for facet in self.column_facets:
            for value, count in self._run(self._column_query(facet)):
                results.append({"facetKey": facet.key, "value": value, "count": count})
        return LogsQueryResponse(results=results)
