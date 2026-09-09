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
    """Values and cross-filtered counts for a column facet, or for a set of attribute keys.

    Attribute keys are always taken as a list, and one list of any length is one query. The
    presentation layer turns a single-key request into a one-key list, so there is no separate
    single-facet path here to drift from the shared one.

    A column facet (severity_text/service_name) groups the logs table directly. An attribute facet —
    a resource attribute like k8s.namespace.name, or a log-body attribute like log.iostream — reads
    the pre-aggregated log_attributes rollup instead of the logs Map column: orders of magnitude
    cheaper, and the only way to keep the query under the read cap at scale.

    Several attribute keys can share one query, because they all apply the same WHERE and the
    rollup's sort key orders attribute_key behind resource_fingerprint — so a single-key query
    already prunes only on (team_id, attribute_type, time_bucket) and reads about the same granules
    as a query over many keys. A rail full of attribute facets therefore costs one query, not one
    per facet.

    What sharing gives up is the per-facet part, which is why `own_facet_semantics` exists. A facet
    asked for on its own excludes its own resource-attribute filter (so selecting a value re-scopes
    its siblings rather than collapsing itself) and honours `facet_search`. Neither is expressible
    across a set of keys, so the flag is rejected for a list of more than one.

    Cross-filtering is exact for column facets, which strip their own WHERE clause. On the rollup it
    depends on what the rollup carries: every attribute facet honours service_name, severity levels
    and resource-attribute filters, but not body search or log-attribute filters — those dimensions
    aren't there. And only a resource-attribute facet can strip its own filter, because rollup rows
    for a resource key share a resource_fingerprint; log attributes have no equivalent grouping
    column, so a log-attribute facet can't exclude itself.
    """

    query: LogsQuery
    cached_response: CachedLogsQueryResponse

    def __init__(
        self,
        query: LogsQuery,
        *args,
        facet_field: str | None = None,
        facet_resource_attributes: list[str] | None = None,
        facet_attributes: list[str] | None = None,
        own_facet_semantics: bool = False,
        facet_search: str | None = None,
        **kwargs,
    ):
        super().__init__(query, *args, **kwargs)
        facets = [
            *[_AttributeFacet(attribute_type="resource", key=key) for key in facet_resource_attributes or []],
            *[_AttributeFacet(attribute_type="log", key=key) for key in facet_attributes or []],
        ]
        # A request targets a top-level column or a set of attribute keys — the two read different
        # tables, so they can't share a query.
        if bool(facet_field) == bool(facets):
            raise ValueError("Provide either facet_field or at least one attribute key")
        if facet_field is not None and facet_field not in FACET_FIELDS:
            raise ValueError(f"Unsupported facet field: {facet_field!r}")
        if len(facets) > MAX_BATCH_FACETS:
            raise ValueError(f"At most {MAX_BATCH_FACETS} attribute keys may be requested, got {len(facets)}")
        # Both per-facet behaviours name one key: an exclusion targets a single attribute, and a
        # type-ahead filters a single value list. Neither is expressible across a set.
        if own_facet_semantics and len(facets) > 1:
            raise ValueError("own_facet_semantics applies to a single attribute key")

        self.facet_field = facet_field
        # Frozen and hashable, so this dedupes while keeping the caller's order for the response.
        self.facets = list(dict.fromkeys(facets))
        # Set by the presentation layer when the caller asked for one facet on its own, which is what
        # earns it the two per-facet behaviours: excluding its own filter, and applying facet_search.
        # A column facet always has them, having no set to share with.
        self.own_facet_semantics = own_facet_semantics or not facets
        # Type-ahead over the facet's *own* values (e.g. service name contains "kafka"), distinct from
        # query.searchTerm which searches log bodies. Lets a dynamic facet search past the LIMIT window.
        self.facet_search = (facet_search or "").strip() or None

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        if self.facets:
            # The rollup is small; "break" returns partial results instead of erroring if we ever
            # hit the cap (mirrors LogValuesQueryRunner). The cap is not scaled by key count: a
            # query over many keys reads roughly what one key reads, so scaling it would allow
            # more than the worst case it replaces.
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
        rows = response.results or []

        # One response shape for every request shape, so a caller reads the same three keys whether
        # it asked for one facet or twenty.
        if not self.facets:
            return LogsQueryResponse(
                results={
                    "facetField": [{"value": row[0], "count": row[1]} for row in rows],
                    "facetResourceAttributes": [],
                    "facetAttributes": [],
                }
            )

        # Seeded so a key the rollup has no rows for comes back as an explicit empty list rather
        # than missing from the response.
        grouped: dict[tuple[str, str], list[dict]] = {(f.attribute_type, f.key): [] for f in self.facets}
        for row in rows:
            grouped.setdefault((row[0], row[1]), []).append({"value": row[2], "count": row[3]})

        def entries(attribute_type: str) -> list[dict]:
            return [
                {"key": key, "values": values}
                for (row_type, key), values in grouped.items()
                if row_type == attribute_type
            ]

        return LogsQueryResponse(
            results={
                "facetField": [],
                "facetResourceAttributes": entries("resource"),
                "facetAttributes": entries("log"),
            }
        )

    def to_query(self) -> ast.SelectQuery:
        return self._column_facet_query() if not self.facets else self._attribute_query()

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

    def _rollup_where_exprs(self, *, exclude_resource_attribute: str | None) -> list[ast.Expr]:
        return _attribute_where_exprs(
            self.query,
            self.team,
            self._attributes_query_date_range,
            exclude_resource_attribute=exclude_resource_attribute,
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

    def _attribute_query(self) -> ast.SelectQuery:
        # Served from the pre-aggregated log_attributes rollup (sum(attribute_count)) rather than
        # grouping the logs Map column, which reads the whole attribute column and blows past the
        # read cap at scale. The rollup carries severity_text and service_name, so severity levels,
        # service_name and resource-attribute filters re-scope the counts; body-search, log-attribute
        # filters and personId / sessionId scoping still aren't in the rollup.
        #
        # One query whatever the key count. The row_number window is what lets each key keep its own
        # top-N, so the counts a key returns don't depend on how many keys it was asked for
        # alongside. With one key it costs a full sort where a plain LIMIT would let ClickHouse stop
        # at 100, but the GROUP BY above it already materialised every group either way.
        date_range = self._attributes_query_date_range
        # Only a lone resource-attribute facet excludes its own key, so selecting a value re-scopes
        # its siblings rather than collapsing itself. A log-attribute facet has nothing to exclude
        # here — its own filter isn't a resource one, and the rollup never applies it. A set of keys
        # shares one WHERE, which is the trade it makes for costing one query.
        own_key = self.facets[0] if self.own_facet_semantics else None
        exclude = own_key.key if own_key and own_key.attribute_type == "resource" else None
        where_exprs = self._rollup_where_exprs(exclude_resource_attribute=exclude)

        counts = parse_select(
            """
            SELECT attribute_type, attribute_key, attribute_value AS value, sum(attribute_count) AS value_count
            FROM log_attributes
            WHERE time_bucket >= {date_from_start_of_interval}
            AND time_bucket <= {date_to_start_of_interval} + {one_interval_period}
            AND {targets}
            AND attribute_value != ''
            AND attribute_value ILIKE {search}
            AND {where}
            GROUP BY attribute_type, attribute_key, attribute_value
            """,
            placeholders={
                "targets": self._targets_expr(),
                # ilike_pattern(None) -> '%', i.e. match every value. A search only ever accompanies
                # a lone facet, so filtering pre-aggregation can't narrow a sibling key.
                "search": ast.Constant(value=ilike_pattern(self.facet_search if own_key else None)),
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
                "limit": ast.Constant(value=self.query.limit or DEFAULT_FACET_LIMIT),
                "total_limit": ast.Constant(value=(self.query.limit or DEFAULT_FACET_LIMIT) * len(self.facets)),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query
