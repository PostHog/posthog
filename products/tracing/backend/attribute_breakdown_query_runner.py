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
        self.modifiers.convertToProjectTimezone = False
        self.modifiers.propertyGroupsMode = PropertyGroupsMode.OPTIMIZED
        self._extract_filters()

    def _calculate(self) -> TraceSpansAttributeBreakdownQueryResponse:
        current_rows, previous_rows = self._run_with_compare()
        return TraceSpansAttributeBreakdownQueryResponse(results=current_rows, compare=previous_rows)

    def _build_query(self, query_date_range: QueryDateRange) -> ast.SelectQuery:
        if self.query.breakdownType == TraceSpanBreakdownType.SPAN_RESOURCE_ATTRIBUTE:
            # resource_attributes' property group matches any key as-is.
            breakdown_chain: list[str | int] = ["resource_attributes", self.query.breakdownKey]
        else:
            # Span attribute keys carry a type suffix in the physical map (attributes_map_str);
            # the property-group resolver only rewrites suffixed keys to map access — a bare key
            # falls through to a JSON read, which is illegal on the Map column. Every value is
            # present in the __str map (the float/datetime maps are derived from it).
            breakdown_chain = ["attributes", f"{self.query.breakdownKey}__str"]
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
            + """ DESC
            LIMIT {limit}
            """,
            placeholders={
                "breakdown_field": ast.Field(chain=breakdown_chain),
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
    person_id: str | None = None,
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
        personId=person_id,
    )
    runner = TraceSpansAttributeBreakdownQueryRunner(query, team)
    response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
    assert isinstance(
        response, TraceSpansAttributeBreakdownQueryResponse | CachedTraceSpansAttributeBreakdownQueryResponse
    )
    return response
