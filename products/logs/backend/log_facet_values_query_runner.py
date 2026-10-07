import datetime as dt
from dataclasses import dataclass
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

# Every facet reads a pre-aggregated rollup (logs_volume_buckets for column facets,
# log_attributes for attribute facets); cap the read and return partial results rather than
# erroring, matching LogValuesQueryRunner.
MAX_ROLLUP_READ_BYTES = 5_000_000_000


@dataclass(frozen=True, kw_only=True)
class _AttributeFacet:
    """A facet over an attribute map key, served from the log_attributes rollup.

    `attribute_type` is the rollup's own discriminator: 'resource' for OTel resource attributes,
    'log' for log-body attributes. Both fields are strings, so keyword-only construction keeps
    them from being swapped at the call site.
    """

    attribute_type: str
    key: str


class LogFacetValuesQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Per-value counts for a single facet.

    A column facet (severity_text/service_name) groups the pre-aggregated logs_volume_buckets
    rollup, which carries both dimensions directly. An attribute facet — a resource attribute like
    k8s.namespace.name, or a log-body attribute like log.iostream — reads the pre-aggregated
    log_attributes rollup instead. Both rollups are orders of magnitude cheaper than grouping the
    logs table itself, and the only way to keep the query under the read cap at scale.

    Cross-filtering (a facet's counts reflect every *other* active filter, so selecting a value
    re-scopes its siblings rather than itself) depends on what each rollup carries. A column facet
    strips its own WHERE clause exactly, since logs_volume_buckets carries service_name and
    severity_text as real dimensions; it does not honour body search, log-attribute filters, or
    resource-attribute filters, which aren't in that rollup. Every attribute facet honours
    service_name, severity levels and resource-attribute filters, but not body search or
    log-attribute filters — those dimensions aren't there either. And only a resource-attribute
    facet can strip its own filter, because rollup rows for a resource key share a
    resource_fingerprint; log attributes have no equivalent grouping column, so a log-attribute
    facet can't exclude itself.

    personId/sessionId scoping (the person/session-scoped Logs tab) isn't in either rollup, and
    unlike the other gaps above it must stay exact — those views exist to show only one person's
    or session's own lines. So a column facet falls back to grouping the logs table directly
    whenever personId or sessionId is set; the rollup path only serves the common unscoped case.
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
        # A facet targets a top-level column (severity_text/service_name), a resource attribute map
        # key (e.g. k8s.namespace.name), or a log-body attribute map key (e.g. log.iostream).
        # Exactly one must be supplied.
        if sum(1 for target in (facet_field, facet_resource_attribute, facet_attribute) if target) != 1:
            raise ValueError("Provide exactly one of facet_field, facet_resource_attribute or facet_attribute")
        if facet_field is not None and facet_field not in FACET_FIELDS:
            raise ValueError(f"Unsupported facet field: {facet_field!r}")
        self.facet_field = facet_field
        self.attribute_facet: _AttributeFacet | None = None
        if facet_resource_attribute:
            self.attribute_facet = _AttributeFacet(attribute_type="resource", key=facet_resource_attribute)
        elif facet_attribute:
            self.attribute_facet = _AttributeFacet(attribute_type="log", key=facet_attribute)
        # Type-ahead over the facet's *own* values (e.g. service name contains "kafka"), distinct from
        # query.searchTerm which searches log bodies. Lets a dynamic facet search past the LIMIT window.
        self.facet_search = (facet_search or "").strip() or None

    def get_cache_payload(self) -> dict:
        # Runner arguments, not query fields, so the base payload cannot see them.
        attribute = self.attribute_facet
        return {
            **super().get_cache_payload(),
            "facet_field": self.facet_field,
            "facet_attribute": None if attribute is None else [attribute.attribute_type, attribute.key],
            "facet_search": self.facet_search,
        }

    @cached_property
    def _scoped_to_person_or_session(self) -> bool:
        return self.query.personId is not None or self.query.sessionId is not None

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        if self.facet_field is not None and self._scoped_to_person_or_session:
            # personId/sessionId scoping isn't in logs_volume_buckets, so this falls back to
            # grouping the logs table directly — fail fast rather than scan unbounded data.
            return HogQLGlobalSettings(
                max_execution_time=30,
                max_bytes_to_read=10_000_000_000,
                read_overflow_mode="throw",
            )
        # Every other facet reads a small pre-aggregated rollup; "break" returns partial results
        # instead of erroring if a very large window ever hits the cap (mirrors LogValuesQueryRunner).
        return HogQLGlobalSettings(
            read_overflow_mode="break",
            max_bytes_to_read=MAX_ROLLUP_READ_BYTES,
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

    @cached_property
    def _volume_buckets_query_date_range(self) -> QueryDateRange:
        # logs_volume_buckets is bucketed at 5-minute granularity; align bounds to it.
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=IntervalType.MINUTE,
            interval_count=5,
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
        if self.attribute_facet is not None:
            return self._attribute_query(self.attribute_facet)
        if self._scoped_to_person_or_session:
            return self._column_facet_query_from_logs()
        return self._column_facet_query_from_rollup()

    def _column_facet_query_from_rollup(self) -> ast.SelectQuery:
        # Served from the pre-aggregated logs_volume_buckets rollup (sum(log_count)) rather than
        # grouping the logs table, which reads every row in the window and blows past the read cap
        # at scale. The rollup carries service_name and severity_text directly, so this facet can
        # still strip its own filter exactly (exclude_facet_field); it does not carry body search,
        # log-attribute filters, or resource-attribute filters, so those aren't applied here. Never
        # called when personId/sessionId is set — to_query() routes that to
        # _column_facet_query_from_logs instead, since the rollup can't scope to either.
        facet = ast.Field(chain=[cast(str, self.facet_field)])
        filter_builder = LogsFilterBuilder(
            self.query,
            self.team,
            self.query_date_range,
            exclude_facet_field=self.facet_field,
        )
        date_range = self._volume_buckets_query_date_range
        exprs: list[ast.Expr] = [
            parse_expr(
                "time_bucket >= {date_from} AND time_bucket < {date_to}",
                placeholders={
                    "date_from": ast.Constant(value=date_range.date_from()),
                    "date_to": ast.Constant(value=date_range.date_to()),
                },
            ),
        ]
        if self.query.serviceNames and self.facet_field != "service_name":
            exprs.append(
                parse_expr(
                    "service_name IN {serviceNames}",
                    placeholders={
                        "serviceNames": ast.Tuple(exprs=[ast.Constant(value=str(sn)) for sn in self.query.serviceNames])
                    },
                )
            )
        if self.query.severityLevels and self.facet_field != "severity_text":
            exprs.append(
                parse_expr(
                    "severity_text IN {severityLevels}",
                    placeholders={
                        "severityLevels": ast.Tuple(
                            exprs=[ast.Constant(value=str(sl)) for sl in self.query.severityLevels]
                        )
                    },
                )
            )
        # Level and service also arrive as `log` filters in filterGroup, which is where the viewer
        # keeps a facet selection; column_filter_exprs() strips this facet's own key already.
        exprs.extend(filter_builder.column_filter_exprs())
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
            SELECT {facet} AS value, sum(log_count) AS count
            FROM posthog.logs_volume_buckets
            WHERE {where}
            GROUP BY {facet}
            ORDER BY sum(log_count) DESC, {facet} ASC
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

    def _column_facet_query_from_logs(self) -> ast.SelectQuery:
        # personId/sessionId scoping isn't in logs_volume_buckets, so a person- or session-scoped
        # Logs tab falls back to grouping the logs table directly, exactly as every column facet
        # did before that rollup existed. Narrower than the unscoped case this bypasses: bounded to
        # one person's or session's own lines, not a full team-wide scan.
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

    def _attribute_query(self, facet: _AttributeFacet) -> ast.SelectQuery:
        # Served from the pre-aggregated log_attributes rollup (sum(attribute_count)) rather than
        # grouping the logs Map column, which reads the whole attribute column and blows past the
        # read cap at scale. The rollup carries severity_text and service_name, so severity levels,
        # service_name and resource-attribute filters re-scope the counts; body-search, log-attribute
        # filters and personId / sessionId scoping still aren't in the rollup.
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
        if self.query.severityLevels:
            where_exprs.append(
                parse_expr(
                    "severity_text IN {severityLevels}",
                    placeholders={
                        "severityLevels": ast.Tuple(
                            exprs=[ast.Constant(value=str(sl)) for sl in self.query.severityLevels]
                        )
                    },
                )
            )
        # Cross-filter by resource attributes. A resource-attribute facet excludes its own key so
        # selecting a value doesn't collapse the facet to that single value; a log-attribute facet
        # has nothing to exclude here, since its own filter isn't a resource one.
        filter_builder = LogsFilterBuilder(
            self.query,
            self.team,
            date_range,
            exclude_resource_attribute=facet.key if facet.attribute_type == "resource" else None,
        )
        # Level and service also arrive as `log` filters in filterGroup, which is where the viewer
        # keeps a facet selection. Nothing is stripped here: an attribute facet never owns a column,
        # and a column facet is served by _column_facet_query_from_rollup/_column_facet_query_from_logs,
        # both of which pass exclude_facet_field.
        where_exprs.extend(filter_builder.column_filter_exprs())
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
                "attribute_type": ast.Constant(value=facet.attribute_type),
                "attribute_key": ast.Constant(value=facet.key),
                # ilike_pattern(None) -> '%', i.e. match every value when no facet search is given.
                "search": ast.Constant(value=ilike_pattern(self.facet_search)),
                "where": ast.And(exprs=where_exprs),
                "limit": ast.Constant(value=self.query.limit or DEFAULT_FACET_LIMIT),
                **date_range.to_placeholders(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query
