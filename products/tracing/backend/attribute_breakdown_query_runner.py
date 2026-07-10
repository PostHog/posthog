from typing import TYPE_CHECKING

from posthog.schema import (
    AttributeBreakdownRow,
    CachedTraceSpansAttributeBreakdownQueryResponse,
    CompareFilter,
    DateRange,
    PropertyGroupFilter,
    PropertyGroupsMode,
    TraceSpanBreakdownOrderBy,
    TraceSpanBreakdownType,
    TraceSpansAttributeBreakdownQuery,
    TraceSpansAttributeBreakdownQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, ExecutionMode
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.tracing.backend.aggregation_query_runner import _ROW_LIMIT, _SpanAggregationMixin
from products.tracing.backend.logic import TIME_BUCKET_DATE_RANGE_WHERE

if TYPE_CHECKING:
    from posthog.models import Team

# Validated enum value → ClickHouse ORDER BY column. Lookup keeps user input out of the SQL string.
_ORDER_COLUMNS: dict[TraceSpanBreakdownOrderBy, str] = {
    TraceSpanBreakdownOrderBy.COUNT: "count",
    TraceSpanBreakdownOrderBy.ERROR_COUNT: "error_count",
}

# Top-level columns the `span` breakdown type may group by. The allowlist (enforced at both the
# API and runner level) keeps arbitrary column names out of the generated SQL.
FACET_COLUMNS: frozenset[str] = frozenset({"service_name", "status_code"})


class TraceSpansAttributeBreakdownQueryRunner(
    _SpanAggregationMixin, AnalyticsQueryRunner[TraceSpansAttributeBreakdownQueryResponse]
):
    """Span counts grouped by one attribute's value — the "what's different" facet primitive.

    Single-table ``GROUP BY`` on a span or resource attribute value within a filtered span
    set. One row per distinct value; spans without the attribute group under ``''``.
    """

    query: TraceSpansAttributeBreakdownQuery
    cached_response: CachedTraceSpansAttributeBreakdownQueryResponse

    def __init__(self, query: TraceSpansAttributeBreakdownQuery, *args, **kwargs) -> None:
        super().__init__(query, *args, **kwargs)
        if self.query.breakdownType == TraceSpanBreakdownType.SPAN and self.query.breakdownKey not in FACET_COLUMNS:
            raise ValueError(f"Unsupported span column for breakdown: {self.query.breakdownKey!r}")
        self.modifiers.convertToProjectTimezone = False
        self.modifiers.propertyGroupsMode = PropertyGroupsMode.OPTIMIZED
        self._extract_filters()

    def _extract_filters(self) -> None:
        super()._extract_filters()
        if not self.query.excludeBreakdownFilter:
            return
        # Facet semantics: a facet's value list must ignore its own selection (otherwise selecting
        # a value collapses the facet to one row), while all other filters still apply.
        key = self.query.breakdownKey
        if self.query.breakdownType == TraceSpanBreakdownType.SPAN:
            self.span_filters = [f for f in self.span_filters if f.key != key]
            if key == "service_name":
                # The dedicated service filter targets the same column as the breakdown.
                self.query.serviceNames = None
        elif self.query.breakdownType == TraceSpanBreakdownType.SPAN_ATTRIBUTE:
            # Extraction suffixed the keys with their physical-map type (`__str` / `__float`).
            suffixed = {f"{key}__str", f"{key}__float"}
            self.span_attribute_filters = [f for f in self.span_attribute_filters if f.key not in suffixed]
        else:
            self.resource_attribute_filters = [f for f in self.resource_attribute_filters if f.key != key]

    def _calculate(self) -> TraceSpansAttributeBreakdownQueryResponse:
        current_rows, previous_rows = self._run_with_compare()
        return TraceSpansAttributeBreakdownQueryResponse(results=current_rows, compare=previous_rows)

    def _build_query(self, query_date_range: QueryDateRange) -> ast.SelectQuery:
        breakdown_field: ast.Expr
        if self.query.breakdownType == TraceSpanBreakdownType.SPAN:
            # Allowlisted top-level column (validated in __init__). toString keeps the response
            # shape uniform — status_code is an Int16 (0/1/2) but rows always carry string values.
            breakdown_field = ast.Call(name="toString", args=[ast.Field(chain=[self.query.breakdownKey])])
        elif self.query.breakdownType == TraceSpanBreakdownType.SPAN_RESOURCE_ATTRIBUTE:
            # resource_attributes' property group matches any key as-is.
            breakdown_field = ast.Field(chain=["resource_attributes", self.query.breakdownKey])
        else:
            # Span attribute keys carry a type suffix in the physical map (attributes_map_str);
            # the property-group resolver only rewrites suffixed keys to map access — a bare key
            # falls through to a JSON read, which is illegal on the Map column. Every value is
            # present in the __str map (the float/datetime maps are derived from it).
            breakdown_field = ast.Field(chain=["attributes", f"{self.query.breakdownKey}__str"])
        order_column = _ORDER_COLUMNS[self.query.orderBy or TraceSpanBreakdownOrderBy.COUNT]

        query = parse_select(
            """
            SELECT
                {breakdown_field} AS value,
                count() AS count,
                countIf(status_code = 2) AS error_count,
                quantile(0.5)(duration_nano) AS p50_duration_nano,
                quantile(0.95)(duration_nano) AS p95_duration_nano
            FROM posthog.trace_spans
            WHERE {where}
              AND """
            + TIME_BUCKET_DATE_RANGE_WHERE
            + """
              AND timestamp >= {date_from}
              AND timestamp < {date_to}
            GROUP BY value
            ORDER BY """
            + order_column
            + """ DESC, value ASC
            LIMIT {limit}
            """,
            placeholders={
                "breakdown_field": breakdown_field,
                "where": self._where_without_date_range(),
                "limit": ast.Constant(value=_ROW_LIMIT),
                **query_date_range.to_placeholders(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _row_from_clickhouse(self, row: list) -> AttributeBreakdownRow:
        return AttributeBreakdownRow(
            value=row[0] or "",
            count=row[1],
            error_count=row[2] or 0,
            p50_duration_nano=float(row[3] or 0),
            p95_duration_nano=float(row[4] or 0),
        )


def run_attribute_breakdown_query(
    *,
    team: "Team",
    date_range: DateRange,
    breakdown_key: str,
    breakdown_type: TraceSpanBreakdownType,
    order_by: TraceSpanBreakdownOrderBy | None = None,
    compare_filter: CompareFilter | None = None,
    filter_group: PropertyGroupFilter | None = None,
    service_names: list[str] | None = None,
    exclude_breakdown_filter: bool = False,
) -> TraceSpansAttributeBreakdownQueryResponse | CachedTraceSpansAttributeBreakdownQueryResponse:
    """Facade-friendly entry point for running an attribute breakdown query."""
    query = TraceSpansAttributeBreakdownQuery(
        dateRange=date_range,
        breakdownKey=breakdown_key,
        breakdownType=breakdown_type,
        orderBy=order_by,
        compareFilter=compare_filter,
        filterGroup=filter_group,
        serviceNames=service_names,
        excludeBreakdownFilter=exclude_breakdown_filter,
    )
    runner = TraceSpansAttributeBreakdownQueryRunner(query, team)
    response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
    assert isinstance(
        response, TraceSpansAttributeBreakdownQueryResponse | CachedTraceSpansAttributeBreakdownQueryResponse
    )
    return response
