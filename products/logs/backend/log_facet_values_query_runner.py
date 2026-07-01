import datetime as dt
from functools import cached_property
from typing import cast
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

# Columns a facet may group by. Each value is also the WHERE clause that gets omitted, so a facet's
# counts reflect every *other* active filter rather than its own selection.
FACET_FIELDS: frozenset[str] = frozenset({"severity_text", "service_name"})

DEFAULT_FACET_LIMIT = 100

# Resource-attribute facets read the pre-aggregated log_attributes rollup; cap the read and return
# partial results rather than erroring, matching LogValuesQueryRunner.
MAX_RESOURCE_READ_BYTES = 5_000_000_000


class LogFacetValuesQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Per-value counts for a single facet.

    A column facet (severity_text/service_name) groups the logs table directly. A resource-attribute
    facet (e.g. k8s.namespace.name) reads the pre-aggregated log_attributes rollup instead of the
    logs Map column — orders of magnitude cheaper, and the only way to keep the query under the read
    cap at scale. Both exclude the facet's own filter so selecting a value re-scopes the *other*
    facets. Resource-attribute facet counts honour service_name and other resource-attribute filters
    but not severity / body-search / log-attribute filters (those dimensions aren't in the rollup).
    """

    query: LogsQuery
    cached_response: CachedLogsQueryResponse

    def __init__(
        self,
        query: LogsQuery,
        *args,
        facet_field: str | None = None,
        facet_resource_attribute: str | None = None,
        facet_search: str | None = None,
        **kwargs,
    ):
        super().__init__(query, *args, **kwargs)
        # A facet targets either a top-level column (severity_text/service_name) or a resource
        # attribute map key (e.g. k8s.namespace.name). Exactly one must be supplied.
        if bool(facet_field) == bool(facet_resource_attribute):
            raise ValueError("Provide exactly one of facet_field or facet_resource_attribute")
        if facet_field is not None and facet_field not in FACET_FIELDS:
            raise ValueError(f"Unsupported facet field: {facet_field!r}")
        self.facet_field = facet_field
        self.facet_resource_attribute = facet_resource_attribute
        # Type-ahead over the facet's *own* values (e.g. service name contains "kafka"), distinct from
        # query.searchTerm which searches log bodies. Lets a dynamic facet search past the LIMIT window.
        self.facet_search = (facet_search or "").strip() or None

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        if self.facet_resource_attribute is not None:
            # The rollup is small; "break" returns partial results instead of erroring if we ever
            # hit the cap (mirrors LogValuesQueryRunner).
            return HogQLGlobalSettings(
                read_overflow_mode="break",
                max_bytes_to_read=MAX_RESOURCE_READ_BYTES,
            )
        # Column facets still group the logs table — fail fast rather than scan unbounded data.
        return HogQLGlobalSettings(
            max_execution_time=30,
            max_bytes_to_read=10_000_000_000,
            read_overflow_mode="throw",
        )

    @cached_property
    def _attributes_query_date_range(self) -> QueryDateRange:
        # log_attributes is bucketed at 10-minute granularity; align bounds to it.
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=IntervalType.MINUTE,
            interval_count=10,
            now=dt.datetime.now(),
            timezone_info=ZoneInfo("UTC"),
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
        if self.facet_resource_attribute is not None:
            return self._resource_attribute_query()
        return self._column_facet_query()

    def _column_facet_query(self) -> ast.SelectQuery:
        # The day-precision time_bucket prune in where() is widened to exact timestamp bounds so the
        # counts match the requested window (same half-open pattern as CountQueryRunner).
        facet = ast.Field(chain=[cast(str, self.facet_field)])
        filter_builder = LogsFilterBuilder(
            self.query,
            self.team,
            self.query_date_range,
            exclude_facet_field=self.facet_field,
        )
        exprs = [
            filter_builder.where(),
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
                    "{facet} ILIKE {pattern}",
                    placeholders={
                        "facet": facet,
                        # Escape %, _ and \ so user input matches literally instead of as wildcards.
                        "pattern": ast.Constant(value=ilike_pattern(self.facet_search)),
                    },
                )
            )
        query = parse_select(
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
                "limit": ast.Constant(value=self.query.limit or DEFAULT_FACET_LIMIT),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _resource_attribute_query(self) -> ast.SelectQuery:
        # Served from the pre-aggregated log_attributes rollup (sum(attribute_count)) rather than
        # grouping the logs Map column, which reads the whole resource_attributes column and blows
        # past the read cap at scale. The rollup has no severity/body/log-attribute dimension, so only
        # service_name and other resource-attribute filters re-scope the counts.
        date_range = self._attributes_query_date_range
        where_exprs: list[ast.Expr] = []
        if self.query.serviceNames:
            where_exprs.append(
                parse_expr(
                    "service_name IN {serviceNames}",
                    placeholders={
                        "serviceNames": ast.Tuple(exprs=[ast.Constant(value=str(sn)) for sn in self.query.serviceNames])
                    },
                )
            )
        # Cross-filter by other resource attributes, excluding this facet's own key so selecting a
        # value doesn't collapse the facet to that single value.
        filter_builder = LogsFilterBuilder(
            self.query,
            self.team,
            date_range,
            exclude_resource_attribute=self.facet_resource_attribute,
        )
        where_exprs.append(filter_builder.resource_filter(existing_filters=where_exprs))

        query = parse_select(
            """
            SELECT attribute_value AS value, sum(attribute_count) AS count
            FROM log_attributes
            WHERE time_bucket >= {date_from_start_of_interval}
            AND time_bucket <= {date_to_start_of_interval} + {one_interval_period}
            AND attribute_type = {attribute_type}
            AND attribute_key = {attribute_key}
            AND attribute_value != ''
            AND attribute_value ILIKE {search}
            AND {where}
            GROUP BY attribute_value
            ORDER BY sum(attribute_count) DESC, attribute_value ASC
            LIMIT {limit}
            """,
            placeholders={
                "attribute_type": ast.Constant(value="resource"),
                "attribute_key": ast.Constant(value=cast(str, self.facet_resource_attribute)),
                # ilike_pattern(None) -> '%', i.e. match every value when no facet search is given.
                "search": ast.Constant(value=ilike_pattern(self.facet_search)),
                "where": ast.And(exprs=where_exprs),
                "limit": ast.Constant(value=self.query.limit or DEFAULT_FACET_LIMIT),
                **date_range.to_placeholders(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query
