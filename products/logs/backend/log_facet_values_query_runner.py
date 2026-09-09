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

# Cap on facets per batch. A rail shows far fewer; this bounds the response and the OR arms.
MAX_BATCH_FACETS = 50

# Attribute facets read the pre-aggregated log_attributes rollup; cap the read and return
# partial results rather than erroring, matching LogValuesQueryRunner.
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


def _attributes_date_range(query: LogsQuery, team: "Team") -> QueryDateRange:
    # log_attributes is bucketed at 10-minute granularity; align bounds to it.
    return QueryDateRange(
        date_range=query.dateRange,
        team=team,
        interval=IntervalType.MINUTE,
        interval_count=10,
        now=dt.datetime.now(),
        timezone_info=ZoneInfo("UTC"),
    )


def _attribute_where_exprs(
    query: LogsQuery,
    team: "Team",
    date_range: QueryDateRange,
    *,
    exclude_resource_attribute: str | None,
) -> list[ast.Expr]:
    """The WHERE terms an attribute facet applies on top of the rollup's own key/type/time bounds.

    Shared by the single-facet and batch runners so the two produce identical filtering — the batch
    is only safe because it can omit `exclude_resource_attribute` for facets that have no filter of
    their own, and that equivalence has to be structural rather than a claim.

    Builds exactly one LogsFilterBuilder: `_generate_resource_attribute_filters` rewrites
    `filter.operator` in place on objects owned by `query.filterGroup` (is_not becomes exact, and so
    on), so a second builder over the same query would read an already-inverted negative filter as a
    positive one and silently return wrong counts.
    """
    exprs: list[ast.Expr] = []
    if query.serviceNames:
        exprs.append(
            parse_expr(
                "service_name IN {serviceNames}",
                placeholders={
                    "serviceNames": ast.Tuple(exprs=[ast.Constant(value=str(sn)) for sn in query.serviceNames])
                },
            )
        )
    if query.severityLevels:
        exprs.append(
            parse_expr(
                "severity_text IN {severityLevels}",
                placeholders={
                    "severityLevels": ast.Tuple(exprs=[ast.Constant(value=str(sl)) for sl in query.severityLevels])
                },
            )
        )
    filter_builder = LogsFilterBuilder(
        query,
        team,
        date_range,
        exclude_resource_attribute=exclude_resource_attribute,
    )
    # Level and service also arrive as `log` filters in filterGroup, which is where the viewer
    # keeps a facet selection. Nothing is stripped here: an attribute facet never owns a column,
    # and a column facet is served by _column_facet_query, which passes exclude_facet_field.
    exprs.extend(filter_builder.column_filter_exprs())
    exprs.append(filter_builder.resource_filter(existing_filters=exprs))
    return exprs


class LogFacetValuesQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Per-value counts for a single facet.

    A column facet (severity_text/service_name) groups the logs table directly. An attribute facet —
    a resource attribute like k8s.namespace.name, or a log-body attribute like log.iostream — reads
    the pre-aggregated log_attributes rollup instead of the logs Map column: orders of magnitude
    cheaper, and the only way to keep the query under the read cap at scale.

    Cross-filtering (a facet's counts reflect every *other* active filter, so selecting a value
    re-scopes its siblings rather than itself) is exact for column facets, which strip their own
    WHERE clause. On the rollup it depends on what the rollup carries. Every attribute facet honours
    service_name, severity levels and resource-attribute filters, but not body search or
    log-attribute filters — those dimensions aren't there. And only a resource-attribute facet can
    strip its own filter, because rollup rows for a resource key share a resource_fingerprint; log
    attributes have no equivalent grouping column, so a log-attribute facet can't exclude itself.
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
        if self.attribute_facet is not None:
            # The rollup is small; "break" returns partial results instead of erroring if we ever
            # hit the cap (mirrors LogValuesQueryRunner).
            return HogQLGlobalSettings(
                read_overflow_mode="break",
                max_bytes_to_read=MAX_ATTRIBUTE_READ_BYTES,
            )
        # Column facets still group the logs table — fail fast rather than scan unbounded data.
        return HogQLGlobalSettings(
            max_execution_time=30,
            max_bytes_to_read=10_000_000_000,
            read_overflow_mode="throw",
        )

    @cached_property
    def _attributes_query_date_range(self) -> QueryDateRange:
        return _attributes_date_range(self.query, self.team)

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

    def _attribute_query(self, facet: _AttributeFacet) -> ast.SelectQuery:
        # Served from the pre-aggregated log_attributes rollup (sum(attribute_count)) rather than
        # grouping the logs Map column, which reads the whole attribute column and blows past the
        # read cap at scale. The rollup carries severity_text and service_name, so severity levels,
        # service_name and resource-attribute filters re-scope the counts; body-search, log-attribute
        # filters and personId / sessionId scoping still aren't in the rollup.
        date_range = self._attributes_query_date_range
        # Cross-filter by resource attributes. A resource-attribute facet excludes its own key so
        # selecting a value doesn't collapse the facet to that single value; a log-attribute facet
        # has nothing to exclude here, since its own filter isn't a resource one.
        where_exprs = _attribute_where_exprs(
            self.query,
            self.team,
            date_range,
            exclude_resource_attribute=facet.key if facet.attribute_type == "resource" else None,
        )

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


class LogAttributeFacetValuesBatchQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Per-value counts for several attribute facets in one scan of the log_attributes rollup.

    Every attribute facet applies the same WHERE clause, and the rollup's sort key orders
    attribute_key behind resource_fingerprint — so a single-key query already prunes only on
    (team_id, attribute_type, time_bucket) and reads about the same granules as a batch over many
    keys. A rail therefore costs one query instead of one per facet.

    Two things vary per facet and neither is expressible here: a facet's own resource-attribute
    filter, which it must exclude to keep cross-filtering, and its type-ahead search. Callers keep
    those facets on LogFacetValuesQueryRunner. Absent both, this returns what the per-facet queries
    would have returned.
    """

    query: LogsQuery
    cached_response: CachedLogsQueryResponse

    def __init__(
        self,
        query: LogsQuery,
        *args,
        facet_resource_attributes: list[str] | None = None,
        facet_attributes: list[str] | None = None,
        **kwargs,
    ):
        super().__init__(query, *args, **kwargs)
        facets = [
            *[_AttributeFacet(attribute_type="resource", key=key) for key in facet_resource_attributes or []],
            *[_AttributeFacet(attribute_type="log", key=key) for key in facet_attributes or []],
        ]
        if not facets:
            raise ValueError("Provide at least one of facet_resource_attributes or facet_attributes")
        if len(facets) > MAX_BATCH_FACETS:
            raise ValueError(f"At most {MAX_BATCH_FACETS} facets may be batched, got {len(facets)}")
        # Frozen and hashable, so this dedupes while keeping the caller's order for the response.
        self.facets = list(dict.fromkeys(facets))

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        # Same cap as the single-facet attribute path rather than one scaled by facet count: the
        # batch reads roughly what one facet reads, so scaling would let it read more than the
        # worst case it replaces.
        return HogQLGlobalSettings(
            read_overflow_mode="break",
            max_bytes_to_read=MAX_ATTRIBUTE_READ_BYTES,
        )

    @cached_property
    def _attributes_query_date_range(self) -> QueryDateRange:
        return _attributes_date_range(self.query, self.team)

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
        # Seeded so a facet the rollup has no rows for comes back as an explicit empty list rather
        # than missing from the response.
        grouped: dict[tuple[str, str], list[dict]] = {(f.attribute_type, f.key): [] for f in self.facets}
        for row in response.results or []:
            grouped.setdefault((row[0], row[1]), []).append({"value": row[2], "count": row[3]})

        def entries(attribute_type: str) -> list[dict]:
            return [
                {"key": key, "values": values}
                for (row_type, key), values in grouped.items()
                if row_type == attribute_type
            ]

        # Split by type rather than tagging each entry, so the response mirrors the request's two
        # key lists and neither side needs an attribute-type enum.
        return LogsQueryResponse(
            results={
                "facetResourceAttributes": entries("resource"),
                "facetAttributes": entries("log"),
            }
        )

    def _targets_expr(self) -> ast.Expr:
        # One OR arm per attribute type, each an `attribute_key IN (...)`. A tuple-IN over
        # (attribute_type, attribute_key) reads the same rows but cannot use idx_attribute_key,
        # the only skip index this table offers for the key.
        arms: list[ast.Expr] = []
        for attribute_type in ("resource", "log"):
            keys = [facet.key for facet in self.facets if facet.attribute_type == attribute_type]
            if not keys:
                continue
            arms.append(
                parse_expr(
                    "attribute_type = {attribute_type} AND attribute_key IN {keys}",
                    placeholders={
                        "attribute_type": ast.Constant(value=attribute_type),
                        "keys": ast.Tuple(exprs=[ast.Constant(value=key) for key in keys]),
                    },
                )
            )
        return arms[0] if len(arms) == 1 else ast.Or(exprs=arms)

    def to_query(self) -> ast.SelectQuery:
        date_range = self._attributes_query_date_range
        where_exprs = _attribute_where_exprs(
            self.query,
            self.team,
            date_range,
            exclude_resource_attribute=None,
        )

        counts = parse_select(
            """
            SELECT attribute_type, attribute_key, attribute_value AS value, sum(attribute_count) AS value_count
            FROM log_attributes
            WHERE time_bucket >= {date_from_start_of_interval}
            AND time_bucket <= {date_to_start_of_interval} + {one_interval_period}
            AND {targets}
            AND attribute_value != ''
            AND {where}
            GROUP BY attribute_type, attribute_key, attribute_value
            """,
            placeholders={
                "targets": self._targets_expr(),
                "where": ast.And(exprs=where_exprs),
                **date_range.to_placeholders(),
            },
        )

        # value_count rather than a `count` alias: the window's ORDER BY has to name the aggregate,
        # and `count` would also resolve as the function.
        query = parse_select(
            """
            SELECT attribute_type, attribute_key, value, value_count AS count
            FROM (
                SELECT attribute_type, attribute_key, value, value_count,
                       row_number() OVER (
                           PARTITION BY attribute_type, attribute_key
                           ORDER BY value_count DESC, value ASC
                       ) AS rn
                FROM {counts}
            )
            WHERE rn <= {limit}
            ORDER BY attribute_type ASC, attribute_key ASC, value_count DESC, value ASC
            LIMIT {total_limit}
            """,
            placeholders={
                "counts": counts,
                # Per facet, matching the single-facet LIMIT, so batching can't change what a facet returns.
                "limit": ast.Constant(value=DEFAULT_FACET_LIMIT),
                "total_limit": ast.Constant(value=DEFAULT_FACET_LIMIT * len(self.facets)),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query
