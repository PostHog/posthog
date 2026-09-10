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

# capture-logs writes this resource attribute on every log, with an empty value when the resource
# omits it. The rollup therefore holds exactly one row group per log under this key, which lets a
# column facet count logs from the rollup without the per-attribute fan-out every other key has.
SERVICE_NAME_RESOURCE_ATTRIBUTE = "service.name"

DEFAULT_FACET_LIMIT = 100

# Facets read the pre-aggregated log_attributes rollup; cap the read and return partial results
# rather than erroring, matching LogValuesQueryRunner.
MAX_ATTRIBUTE_READ_BYTES = 5_000_000_000


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
    """Per-value counts for a single facet, served from the pre-aggregated log_attributes rollup.

    An attribute facet — a resource attribute like k8s.namespace.name, or a log-body attribute like
    log.iostream — sums the rollup rows for its key and groups by attribute_value. A column facet
    (severity_text/service_name) cannot group the rollup as-is: every log fans out into one row per
    attribute, so a plain sum counts each log once per attribute it carries. It instead reads only
    the rows keyed on the service.name resource attribute, which every log has exactly once, and
    groups by the rollup's own severity_text / service_name column. Both paths are orders of
    magnitude cheaper than grouping the logs table, and the only way to stay under the read cap at
    scale.

    Cross-filtering (a facet's counts reflect every *other* active filter, so selecting a value
    re-scopes its siblings rather than itself) depends on what the rollup carries. Every facet
    honours service_name, severity levels and resource-attribute filters, but not body search or
    log-attribute filters — those dimensions aren't there. A column facet strips its own column
    filter, and a resource-attribute facet its own key's filter, because rollup rows for a resource
    key share a resource_fingerprint; log attributes have no equivalent grouping column, so a
    log-attribute facet can't exclude itself.
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

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        # The rollup is small; "break" returns partial results instead of erroring if we ever
        # hit the cap (mirrors LogValuesQueryRunner).
        return HogQLGlobalSettings(
            read_overflow_mode="break",
            max_bytes_to_read=MAX_ATTRIBUTE_READ_BYTES,
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
        if self.attribute_facet is not None:
            # Logs lacking the key read back '' from the map; that bucket is not a real value.
            return self._rollup_query(
                facet=self.attribute_facet,
                value=ast.Field(chain=["attribute_value"]),
                exclude_blank_values=True,
            )
        return self._rollup_query(
            facet=_AttributeFacet(attribute_type="resource", key=SERVICE_NAME_RESOURCE_ATTRIBUTE),
            value=ast.Field(chain=[cast(str, self.facet_field)]),
            exclude_blank_values=False,
        )

    def _rollup_query(self, *, facet: _AttributeFacet, value: ast.Field, exclude_blank_values: bool) -> ast.SelectQuery:
        # sum(attribute_count) over the rollup rows for one key, grouped by `value`: the key's own
        # attribute_value for an attribute facet, or a rollup column for a column facet. The rollup
        # carries severity_text and service_name, so severity levels, service_name and
        # resource-attribute filters re-scope the counts; body-search, log-attribute filters and
        # personId / sessionId scoping still aren't in the rollup.
        date_range = self._attributes_query_date_range
        where_exprs: list[ast.Expr] = []
        if self.query.serviceNames and self.facet_field != "service_name":
            where_exprs.append(
                parse_expr(
                    "service_name IN {serviceNames}",
                    placeholders={
                        "serviceNames": ast.Tuple(exprs=[ast.Constant(value=str(sn)) for sn in self.query.serviceNames])
                    },
                )
            )
        if self.query.severityLevels and self.facet_field != "severity_text":
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
        # selecting a value doesn't collapse the facet to that single value; a log-attribute or
        # column facet has nothing to exclude here, since its own filter isn't a resource one.
        filter_builder = LogsFilterBuilder(
            self.query,
            self.team,
            date_range,
            exclude_facet_field=self.facet_field,
            exclude_resource_attribute=(
                self.attribute_facet.key
                if self.attribute_facet is not None and self.attribute_facet.attribute_type == "resource"
                else None
            ),
        )
        # Level and service also arrive as `log` filters in filterGroup, which is where the viewer
        # keeps a facet selection. exclude_facet_field strips a column facet's own one; an attribute
        # facet never owns a column, so nothing is stripped for it.
        where_exprs.extend(filter_builder.column_filter_exprs())
        where_exprs.append(filter_builder.resource_filter(existing_filters=where_exprs))
        if exclude_blank_values:
            where_exprs.append(parse_expr("attribute_value != ''"))

        query = parse_select(
            """
            SELECT {value} AS value, sum(attribute_count) AS count
            FROM log_attributes
            WHERE time_bucket >= {date_from_start_of_interval}
            AND time_bucket <= {date_to_start_of_interval} + {one_interval_period}
            AND attribute_type = {attribute_type}
            AND attribute_key = {attribute_key}
            AND {value} ILIKE {search}
            AND {where}
            GROUP BY {value}
            ORDER BY sum(attribute_count) DESC, {value} ASC
            LIMIT {limit}
            """,
            placeholders={
                "value": value,
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
