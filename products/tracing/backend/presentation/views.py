"""
DRF views for tracing.

Responsibilities:
- Validate incoming JSON (via serializers)
- Convert JSON to frozen dataclasses
- Call facade methods (facade/api.py)
- Convert frozen dataclasses to JSON responses

No business logic here - that belongs in logic.py via the facade.
"""

import json
import base64

from drf_spectacular.utils import extend_schema
from pydantic import ValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import (
    CachedTraceSpansQueryResponse,
    CompareFilter,
    DateRange,
    ProductKey,
    PropertyGroupFilter,
    SourceSymbol,
    TraceSpanBreakdownOrderBy,
    TraceSpanBreakdownType,
    TraceSpansQuery,
    TraceSpansQueryResponse,
)

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.event_usage import report_user_action
from posthog.hogql_queries.query_runner import ExecutionMode

from ..attribute_breakdown_query_runner import FACET_COLUMNS
from ..facade.api import (
    annotate_self_time,
    run_attribute_breakdown_query,
    run_count_query,
    run_duration_histogram_query,
    run_symbol_stats_query,
)
from ..has_spans_query_runner import team_has_spans
from ..logic import (
    TraceSpansQueryRunner,
    run_aggregation_query,
    run_attribute_names_query,
    run_attribute_values_query,
    run_service_names_query,
    run_tree_query,
)
from ..sparkline_query_runner import TraceSpansSparklineQueryRunner
from .date_window import normalize_tracing_date_range

# Serializers below are used exclusively for OpenAPI spec generation via
# drf-spectacular. They are NOT used for request validation — the existing
# manual parsing in SpansViewSet is unchanged.


class _TracingDateRangeSerializer(serializers.Serializer):
    date_from = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Start of the date range. Accepts ISO 8601 timestamps or relative formats: -1h, -6h, -1d, -7d, etc.",
    )
    date_to = serializers.CharField(
        required=False,
        allow_null=True,
        help_text='End of the date range. Same format as date_from. Omit or null for "now".',
    )


_SPAN_PROPERTY_TYPE_CHOICES = ["span", "span_attribute", "span_resource_attribute"]
_SPAN_STRING_OPERATORS = ["exact", "is_not", "icontains", "not_icontains", "regex", "not_regex"]
_SPAN_NUMERIC_OPERATORS = ["exact", "gt", "lt"]
_SPAN_EXISTENCE_OPERATORS = ["is_set", "is_not_set"]
_SPAN_ALL_OPERATORS = _SPAN_STRING_OPERATORS + _SPAN_NUMERIC_OPERATORS + _SPAN_EXISTENCE_OPERATORS


class _SpanPropertyFilterSerializer(serializers.Serializer):
    key = serializers.CharField(
        help_text='Attribute key. For type "span", use built-in fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). For "span_attribute"/"span_resource_attribute", use the attribute key (e.g. "http.method").',
    )
    type = serializers.ChoiceField(
        choices=_SPAN_PROPERTY_TYPE_CHOICES,
        help_text='"span" filters built-in span fields. "span_attribute" filters span-level attributes. "span_resource_attribute" filters resource-level attributes.',
    )
    operator = serializers.ChoiceField(
        choices=_SPAN_ALL_OPERATORS,
        help_text="Comparison operator.",
    )
    value = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text="Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators.",
    )


class _TracingQueryBodySerializer(serializers.Serializer):
    dateRange = _TracingDateRangeSerializer(
        required=False,
        help_text="Date range for the query. Defaults to last hour.",
    )
    serviceNames = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Filter by service names.",
    )
    statusCodes = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text="Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans.",
    )
    orderBy = serializers.ChoiceField(
        choices=["timestamp", "duration"],
        required=False,
        help_text=(
            "Column to order by. Defaults to timestamp. Ordering by timestamp paginates via the keyset "
            "cursor ('after'); ordering by duration paginates via 'offset'."
        ),
    )
    orderDirection = serializers.ChoiceField(
        choices=["ASC", "DESC"],
        required=False,
        help_text="Order direction. Defaults to DESC (e.g. timestamp+DESC = newest first, duration+DESC = slowest first).",
    )
    filterGroup = serializers.ListField(
        child=_SpanPropertyFilterSerializer(),
        required=False,
        default=[],
        help_text="Property filters for the query.",
    )
    traceId = serializers.CharField(
        required=False,
        help_text="Filter to a specific trace ID (hex string).",
    )
    limit = serializers.IntegerField(
        required=False,
        default=100,
        help_text="Max results (1-1000). Defaults to 100.",
    )
    after = serializers.CharField(
        required=False,
        help_text="Keyset pagination cursor from a previous timestamp-ordered response.",
    )
    offset = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="Pagination offset, used when ordering by a column (e.g. duration). Defaults to 0.",
    )
    rootSpans = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Filter to root spans only. Defaults to true.",
    )
    flatSpans = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Return the matching spans themselves, one row per span (root and child), instead of "
            "collapsing to traces. Use this to search by a child-span attribute (e.g. code.filepath) "
            "without the whole-trace grouping. Distinct from rootSpans. Defaults to false."
        ),
    )
    prefetchSpans = serializers.IntegerField(
        required=False,
        help_text="Number of child spans to prefetch per trace (1-100).",
    )
    excludeAttributes = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Omit the per-span attributes and resource attributes maps from results to keep payloads compact. Defaults to false.",
    )


class _TracingQueryRequestSerializer(serializers.Serializer):
    query = _TracingQueryBodySerializer(help_text="The tracing spans query to execute.")


class _TracingTimeseriesQueryBodySerializer(serializers.Serializer):
    # Shared filter fields for the timeseries actions; deliberately not a subclass of the span-query
    # body, whose result-shaping fields (orderBy, limit, pagination, flatSpans, …) don't apply here.
    dateRange = _TracingDateRangeSerializer(
        required=False,
        help_text="Date range for the query. Defaults to last hour.",
    )
    serviceNames = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Filter by service names.",
    )
    statusCodes = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text="Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans.",
    )
    filterGroup = serializers.ListField(
        child=_SpanPropertyFilterSerializer(),
        required=False,
        default=[],
        help_text="Property filters for the query.",
    )


class _TracingTimeseriesRequestSerializer(serializers.Serializer):
    query = _TracingTimeseriesQueryBodySerializer(help_text="The sparkline / duration-histogram query to execute.")


class _TracingDurationHistogramQueryBodySerializer(_TracingTimeseriesQueryBodySerializer):
    rootSpans = serializers.BooleanField(
        required=False,
        default=True,
        help_text=(
            "When true (default), bucket root-span durations only — a distribution of traces. "
            "When false, bucket every matching span — used with a span name filter for "
            "operation-scoped distributions."
        ),
    )


class _TracingDurationHistogramRequestSerializer(serializers.Serializer):
    query = _TracingDurationHistogramQueryBodySerializer(help_text="The duration-histogram query to execute.")


class _TracingSparklineQueryBodySerializer(_TracingTimeseriesQueryBodySerializer):
    rootSpans = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "When true, count only root spans (one per trace) so the bars reflect the Traces view. "
            "When false (default), count every matching span — the Spans view's volume."
        ),
    )


class _TracingSparklineRequestSerializer(serializers.Serializer):
    query = _TracingSparklineQueryBodySerializer(help_text="The sparkline query to execute.")


class _TracingTraceRequestSerializer(serializers.Serializer):
    dateRange = _TracingDateRangeSerializer(
        required=False,
        help_text="Date range for the query. Defaults to last 24 hours.",
    )
    excludeAttributes = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Omit the per-span attributes and resource attributes maps from results to keep payloads compact. Defaults to false.",
    )
    offset = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="Pagination offset into the trace's spans (ordered by start time ascending). Each page returns up to 2000 spans; pass the response's `nextOffset` to load the next page. Defaults to 0.",
    )


class _TracingServiceNamesQuerySerializer(serializers.Serializer):
    search = serializers.CharField(required=False, help_text="Search filter for service names.")
    dateRange = serializers.CharField(
        required=False,
        help_text='JSON-encoded date range, e.g. \'{"date_from": "-1h"}\'.',
    )


class _TracingAttributesQuerySerializer(serializers.Serializer):
    search = serializers.CharField(required=False, help_text="Search filter for attribute names.")
    search_values = serializers.BooleanField(
        required=False,
        default=False,
        help_text="When true, the search query also matches attribute values (not just keys), so a value such as a trace_id finds the key holding it.",
    )
    attribute_type = serializers.ChoiceField(
        choices=["span_attribute", "span_resource_attribute"],
        required=False,
        help_text='Type of attributes: "span_attribute" for span-level attributes, "span_resource_attribute" for resource-level attributes.',
    )
    limit = serializers.IntegerField(
        required=False, min_value=1, max_value=100, help_text="Max results (default: 100)."
    )
    offset = serializers.IntegerField(required=False, min_value=0, help_text="Pagination offset (default: 0).")


class _TracingAttributeEntrySerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Attribute key name.")
    propertyFilterType = serializers.CharField(
        help_text='Property filter type: "span_attribute" or "span_resource_attribute". Use this as the `type` field when filtering.',
    )
    matchedOn = serializers.ChoiceField(
        choices=["key", "value"],
        help_text='How the search query matched this row: "key" if the attribute key matched, "value" if a value matched.',
    )
    matchedValue = serializers.CharField(
        required=False,
        allow_null=True,
        help_text='Sample matching value — only set when matchedOn is "value".',
    )


class _TracingAttributesResponseSerializer(serializers.Serializer):
    results = _TracingAttributeEntrySerializer(many=True, help_text="Available attribute keys matching the filters.")
    count = serializers.IntegerField(help_text="Total attribute keys matched (lower bound when searching values).")


class _TracingValuesQuerySerializer(serializers.Serializer):
    key = serializers.CharField(help_text="The attribute key to get values for.")
    attribute_type = serializers.ChoiceField(
        choices=["span", "span_attribute", "span_resource_attribute"],
        required=False,
        help_text='Type of attribute: "span" for built-in span fields (e.g. name), "span_attribute" for span-level attributes, "span_resource_attribute" for resource-level attributes.',
    )
    value = serializers.CharField(required=False, help_text="Search filter for attribute values.")
    limit = serializers.IntegerField(
        required=False, min_value=1, max_value=100, help_text="Max results (default: 100)."
    )
    offset = serializers.IntegerField(required=False, min_value=0, help_text="Pagination offset (default: 0).")


class _CompareFilterSerializer(serializers.Serializer):
    compare = serializers.BooleanField(
        required=False,
        default=False,
        help_text="When true, also fetch results for a comparison window and return them under `compare`.",
    )
    compare_to = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Relative date offset for the comparison window (e.g. '-1h', '-1d', '-7d'). Defaults to the immediately previous period of equal length.",
    )


class _TracingAggregationQueryBodySerializer(serializers.Serializer):
    dateRange = _TracingDateRangeSerializer(
        required=False,
        help_text="Date range for the primary window. Defaults to last hour.",
    )
    compareFilter = _CompareFilterSerializer(
        required=False,
        help_text="Optional comparison-window configuration. When omitted, only the primary window is returned.",
    )
    serviceNames = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Filter by service names.",
    )
    filterGroup = serializers.ListField(
        child=_SpanPropertyFilterSerializer(),
        required=False,
        default=[],
        help_text="Property filters applied to spans in both windows.",
    )


class _TracingAggregationRequestSerializer(serializers.Serializer):
    query = _TracingAggregationQueryBodySerializer(help_text="The span aggregation query to execute.")


class _TracingAttributeBreakdownQueryBodySerializer(serializers.Serializer):
    breakdownKey = serializers.CharField(
        required=True,
        help_text='Attribute key to group by (e.g. "server.address", "http.response.status_code"). Discover keys with apm-attributes-list. For the "span" breakdown type, must be one of the allowlisted top-level columns: "service_name", "status_code".',
    )
    breakdownType = serializers.ChoiceField(
        choices=["span", "span_attribute", "span_resource_attribute"],
        help_text='Where the key lives: "span" for allowlisted top-level span columns, "span_attribute" for span-level attributes, "span_resource_attribute" for resource-level attributes.',
    )
    excludeBreakdownFilter = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Drop filters targeting the breakdown key itself (including serviceNames for a service_name breakdown), so a facet's value list stays complete while one of its values is selected.",
    )
    orderBy = serializers.ChoiceField(
        choices=["count", "error_count"],
        required=False,
        help_text="Order rows by span count or error count, descending. Defaults to count.",
    )
    dateRange = _TracingDateRangeSerializer(
        required=False,
        help_text="Date range for the primary window. Defaults to last hour.",
    )
    compareFilter = _CompareFilterSerializer(
        required=False,
        help_text="Optional comparison-window configuration. When omitted, only the primary window is returned.",
    )
    serviceNames = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Filter by service names.",
    )
    filterGroup = serializers.ListField(
        child=_SpanPropertyFilterSerializer(),
        required=False,
        default=[],
        help_text="Property filters scoping the spans the breakdown runs over (e.g. only error spans).",
    )


class _TracingAttributeBreakdownRequestSerializer(serializers.Serializer):
    query = _TracingAttributeBreakdownQueryBodySerializer(help_text="The attribute breakdown query to execute.")


class _TracingTreeQueryBodySerializer(serializers.Serializer):
    spanName = serializers.CharField(
        required=True,
        help_text=(
            "Span name to scope the matched trace set. Required because the "
            "(trace_id, parent_span_id) self-join is unsafe without bounding the matched traces."
        ),
    )
    serviceName = serializers.CharField(
        required=True,
        help_text=(
            "Service name that scopes the returned tree. Applied to the spans CTE so "
            "the call-tree only contains spans from this service, even when matched "
            "traces span multiple services."
        ),
    )
    dateRange = _TracingDateRangeSerializer(
        required=False,
        help_text="Date range for the primary window. Defaults to last hour.",
    )
    compareFilter = _CompareFilterSerializer(
        required=False,
        help_text="Optional comparison-window configuration. When omitted, only the primary window is returned.",
    )
    serviceNames = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Filter by service names.",
    )
    filterGroup = serializers.ListField(
        child=_SpanPropertyFilterSerializer(),
        required=False,
        default=[],
        help_text="Additional property filters applied to spans in both windows.",
    )


class _TracingTreeRequestSerializer(serializers.Serializer):
    query = _TracingTreeQueryBodySerializer(help_text="The span call-tree aggregation query to execute.")


class _HasSpansResponseSerializer(serializers.Serializer):
    hasSpans = serializers.BooleanField(
        help_text="Whether the team has ingested any tracing spans yet. Used to gate the onboarding empty state."
    )


class _TracingCountBodySerializer(serializers.Serializer):
    dateRange = _TracingDateRangeSerializer(
        required=False,
        help_text="Date range for the count. Defaults to last hour.",
    )
    serviceNames = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Filter by service names.",
    )
    statusCodes = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text="Filter by OTel span status codes (0 Unset, 1 OK, 2 Error) — not HTTP status codes. Use [2] to select error spans.",
    )
    filterGroup = serializers.ListField(
        child=_SpanPropertyFilterSerializer(),
        required=False,
        default=[],
        help_text="Property filters for the count.",
    )


class _TracingCountRequestSerializer(serializers.Serializer):
    query = _TracingCountBodySerializer(help_text="The span count query to execute.")


class _TracingCountResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Number of spans matching the filters.")
    traceCount = serializers.IntegerField(
        help_text="Number of distinct traces whose root span matches the filters — the trace count shown in the Traces view."
    )


# Upper bound on symbols per request; each becomes a multiIf branch in the generated query.
_MAX_SYMBOLS = 1000


class _SymbolStatsSymbolSerializer(serializers.Serializer):
    name = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Opaque identifier (e.g. the function name) echoed back on the matching result row.",
    )
    startLine = serializers.IntegerField(min_value=1, help_text="First line of the symbol's range, inclusive.")
    endLine = serializers.IntegerField(min_value=1, help_text="Last line of the symbol's range, inclusive.")


class _SymbolStatsQueryBodySerializer(serializers.Serializer):
    filePath = serializers.CharField(
        help_text=(
            "Repo-relative path of the source file to aggregate (e.g. 'src/flags/flag_matching.rs'). "
            "Matched as a path suffix against the recorded OTel code.file.path / code.filepath, so a "
            "recorded path carrying an extra crate/workspace prefix still matches. Separators are normalized."
        ),
    )
    dateRange = _TracingDateRangeSerializer(
        required=False,
        help_text="Current period to aggregate over; the prior equal-length window is the comparison. Defaults to last 24h.",
    )
    symbols = _SymbolStatsSymbolSerializer(
        many=True,
        required=False,
        help_text=(
            "Optional symbol (function) line ranges, supplied by the client from its own AST/LSP. When "
            "given, each span is attributed to the smallest enclosing range (one row per symbol). When "
            "omitted (or an empty list), spans are aggregated per source line (one row per line); pass a "
            "single whole-file range for a file-level total."
        ),
    )


class _SymbolStatsRequestSerializer(serializers.Serializer):
    query = _SymbolStatsQueryBodySerializer(help_text="The symbol-stats per-symbol aggregation query to execute.")


class _SymbolStatsPeriodSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Number of spans attributed to this symbol in the period.")
    error_count = serializers.IntegerField(help_text="Spans whose OTel status is Error (status_code = 2).")
    sum_duration_nano = serializers.FloatField(
        help_text="Total wall-clock span duration in the period, in nanoseconds (additive across spans)."
    )
    p50_duration_nano = serializers.FloatField(help_text="Median wall-clock span duration, in nanoseconds.")
    p95_duration_nano = serializers.FloatField(help_text="95th-percentile wall-clock span duration, in nanoseconds.")
    p99_duration_nano = serializers.FloatField(help_text="99th-percentile wall-clock span duration, in nanoseconds.")
    busy_count = serializers.IntegerField(
        help_text="Spans in the period carrying an active/busy time attribute. 0 means busy_* are not meaningful."
    )
    p50_busy_nano = serializers.FloatField(
        help_text="Median active (busy) time, in nanoseconds. Excludes awaiting children."
    )
    p95_busy_nano = serializers.FloatField(help_text="95th-percentile active (busy) time, in nanoseconds.")
    p99_busy_nano = serializers.FloatField(help_text="99th-percentile active (busy) time, in nanoseconds.")


class _SymbolStatsRowSerializer(_SymbolStatsPeriodSerializer):
    line = serializers.IntegerField(
        help_text="Bucket anchor: the source line (line mode) or the symbol's startLine (symbol mode)."
    )
    name = serializers.CharField(
        required=False, allow_null=True, help_text="Echoed name from the requested symbol (symbol mode only)."
    )
    end_line = serializers.IntegerField(
        required=False, allow_null=True, help_text="endLine of the matched symbol's range (symbol mode only)."
    )
    previous = _SymbolStatsPeriodSerializer(
        help_text="The same metrics over the immediately-preceding equal-length period."
    )
    count_pct_change = serializers.FloatField(
        allow_null=True,
        help_text=(
            "Percentage change in count vs the previous period (180 = +180%). Null when there is no "
            "baseline (previous count 0). Use `previous.count` — not a null here — to detect a new symbol."
        ),
    )
    p95_duration_pct_change = serializers.FloatField(
        allow_null=True,
        help_text=(
            "Percentage change in p95 duration vs the previous period (180 = +180%). Null when the previous "
            "p95 is 0 (no comparable baseline), which can occur even when previous.count > 0 — do not read "
            "null as 'new symbol'."
        ),
    )


class _SymbolStatsResponseSerializer(serializers.Serializer):
    results = _SymbolStatsRowSerializer(many=True, help_text="One row per bucket, ordered by line ascending.")
    granularity = serializers.ChoiceField(
        choices=["line", "symbol"],
        help_text="Bucketing applied: 'line' when no symbols were supplied, 'symbol' otherwise.",
    )


# Spans returned per page by the single-trace `trace` endpoint. The waterfall fetches the first page
# on open and pages through the rest via infinite scroll (offset pagination, earliest spans first).
TRACE_SPANS_PAGE_SIZE = 2000


def _encode_after_cursor(timestamp: str, **secondary: str) -> str:
    """Encode a keyset `after` cursor as base64(json) of the boundary row's timestamp + secondary id.

    Mirrors TraceSpansQueryRunner._parse_after_cursor on the read side; `secondary` is the tiebreaker
    field (trace_id for the trace list, span_id for the flat span list).
    """
    return base64.b64encode(json.dumps({"timestamp": timestamp, **secondary}).encode("utf-8")).decode("utf-8")


class SpansViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    scope_object = "tracing"
    serializer_class = _FallbackSerializer

    @staticmethod
    def _normalize_filter_group(filter_group: object) -> dict:
        """Normalize a flat filter array (from MCP) to the nested PropertyGroupFilter structure."""
        if isinstance(filter_group, list):
            if len(filter_group) > 0:
                return {"type": "AND", "values": [{"type": "AND", "values": filter_group}]}
            return {"type": "AND", "values": []}
        if isinstance(filter_group, dict):
            return filter_group
        return {"type": "AND", "values": []}

    @extend_schema(parameters=[_TracingServiceNamesQuerySerializer])
    @action(detail=False, methods=["GET"], url_path="service-names", required_scopes=["tracing:read"])
    def service_names(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        search = request.GET.get("search", "")
        try:
            raw_date_range = json.loads(request.GET.get("dateRange", '{"date_from": "-1h"}'))
        except json.JSONDecodeError:
            raw_date_range = {"date_from": "-1h"}
        date_range = self.get_model(normalize_tracing_date_range(raw_date_range), DateRange)

        results = run_service_names_query(team=self.team, date_range=date_range, search=search)
        return Response({"results": results}, status=status.HTTP_200_OK)

    @extend_schema(responses={200: _HasSpansResponseSerializer})
    @action(detail=False, methods=["GET"], url_path="has_spans", required_scopes=["tracing:read"])
    def has_spans(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        has_spans = team_has_spans(self.team)

        report_user_action(
            request.user,
            "tracing has_spans checked",
            {"has_spans": has_spans},
            team=self.team,
            request=request,
        )

        return Response({"hasSpans": has_spans}, status=status.HTTP_200_OK)

    @extend_schema(request=_TracingQueryRequestSerializer)
    @action(detail=False, methods=["POST"], required_scopes=["tracing:read"])
    def query(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = request.data.get("query", {})

        after_cursor = query_data.get("after", None)
        date_range = self.get_model(normalize_tracing_date_range(query_data.get("dateRange")), DateRange)

        order_by = query_data.get("orderBy")
        if order_by not in ("timestamp", "duration"):
            order_by = "timestamp"
        order_direction = query_data.get("orderDirection")
        if order_direction not in ("ASC", "DESC"):
            order_direction = "DESC"

        offset = query_data.get("offset") or 0
        requested_limit = min(query_data.get("limit", 100), 1000)
        prefetch_spans = query_data.get("prefetchSpans", None)
        if prefetch_spans is not None:
            prefetch_spans = min(int(prefetch_spans), 100)
        flat_spans = bool(query_data.get("flatSpans", False))

        filter_group = (
            self.get_model(self._normalize_filter_group(query_data.get("filterGroup")), PropertyGroupFilter)
            if query_data.get("filterGroup")
            else None
        )

        spans_query = TraceSpansQuery(
            dateRange=date_range,
            serviceNames=query_data.get("serviceNames", None),
            statusCodes=query_data.get("statusCodes", None),
            orderBy=order_by,
            orderDirection=order_direction,
            filterGroup=filter_group,
            traceId=query_data.get("traceId", None),
            limit=requested_limit + 1,
            offset=offset,
            after=after_cursor,
            rootSpans=query_data.get("rootSpans", True),
            flatSpans=flat_spans,
            prefetchSpans=prefetch_spans,
            excludeAttributes=query_data.get("excludeAttributes", False),
        )

        runner = TraceSpansQueryRunner(spans_query, self.team)
        response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)
        all_results = list(response.results)

        # Paginate at the trace level. The runner fetched up to requested_limit + 1 traces; decide
        # hasMore on the trace count and drop the spans of the overflow trace. Ordering by timestamp
        # emits a keyset cursor pointing at the last kept trace; ordering by duration paginates via
        # `offset` instead, so no cursor is emitted. The per-trace sort key (`trace_start` /
        # `trace_duration`) is carried on every span row (see TraceSpansQueryRunner.to_query) — read it
        # directly rather than re-deriving over the prefetched spans, which can disagree with the SQL key.
        by_duration = order_by == "duration"
        next_cursor = None

        if flat_spans:
            # Flat mode already returns one row per matching span in sort order, so paginate at the span
            # level: keep the page, decide hasMore on the span count, and (timestamp order only) emit a
            # keyset cursor on the last kept span's (timestamp, span_id).
            has_more = len(all_results) > requested_limit
            results = all_results[:requested_limit]
            if has_more and not by_duration and results:
                last = results[-1]
                next_cursor = _encode_after_cursor(last["timestamp"].isoformat(), span_id=last["span_id"])
        else:
            descending = order_direction == "DESC"
            sort_key = "trace_duration" if by_duration else "trace_start"
            trace_keys: dict[str, object] = {span["trace_id"]: span[sort_key] for span in all_results}

            ordered_traces = sorted(
                trace_keys.items(),
                key=lambda item: (item[1], base64.b64encode(bytes.fromhex(item[0])).decode("ascii")),
                reverse=descending,
            )
            has_more = len(ordered_traces) > requested_limit
            kept_trace_ids = {tid for tid, _ in ordered_traces[:requested_limit]}
            results = [span for span in all_results if span["trace_id"] in kept_trace_ids]

            # Duration ordering paginates via `offset`; only the timestamp keyset emits an `after` cursor.
            if has_more and not by_duration:
                boundary_trace_id, boundary_ts = ordered_traces[requested_limit - 1]
                next_cursor = _encode_after_cursor(boundary_ts.isoformat(), trace_id=boundary_trace_id)

        report_user_action(
            request.user,
            "tracing query executed",
            {
                "traces_count": len({span["trace_id"] for span in results}),
                "spans_count": len(results),
                "flat_spans": flat_spans,
                "has_more": has_more,
                "has_filter_group": bool(query_data.get("filterGroup")),
                "service_names_count": len(query_data.get("serviceNames") or []),
                "status_codes_count": len(query_data.get("statusCodes") or []),
                "order_by": order_by,
                "order_direction": order_direction,
                "is_paginated": bool(after_cursor) or bool(offset),
            },
            team=self.team,
            request=request,
        )

        return Response(
            {
                "results": results,
                "hasMore": has_more,
                "nextCursor": next_cursor,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(request=_TracingCountRequestSerializer, responses={200: _TracingCountResponseSerializer})
    @action(detail=False, methods=["POST"], required_scopes=["tracing:read"])
    def count(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = request.data.get("query", {})

        date_range = self.get_model(normalize_tracing_date_range(query_data.get("dateRange")), DateRange)
        filter_group = (
            self.get_model(self._normalize_filter_group(query_data.get("filterGroup")), PropertyGroupFilter)
            if query_data.get("filterGroup")
            else None
        )

        response = run_count_query(
            team=self.team,
            date_range=date_range,
            service_names=query_data.get("serviceNames", None),
            status_codes=query_data.get("statusCodes", None),
            filter_group=filter_group,
        )

        report_user_action(
            request.user,
            "tracing count queried",
            {
                "has_filter_group": bool(query_data.get("filterGroup")),
                "service_names_count": len(query_data.get("serviceNames") or []),
                "status_codes_count": len(query_data.get("statusCodes") or []),
            },
            team=self.team,
            request=request,
        )

        return Response(response.results, status=status.HTTP_200_OK)

    @extend_schema(request=_SymbolStatsRequestSerializer, responses={200: _SymbolStatsResponseSerializer})
    @action(detail=False, methods=["POST"], url_path="symbol-stats", required_scopes=["tracing:read"])
    def symbol_stats(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = request.data.get("query", {}) or {}

        file_path = query_data.get("filePath")
        if not file_path or not isinstance(file_path, str):
            return Response(
                {"detail": "`filePath` is required for symbol-stats queries."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # symbols is optional: omitted/empty -> per-line aggregation; supplied -> per-symbol ranges.
        symbols: list[SourceSymbol] | None = None
        raw_symbols = query_data.get("symbols")
        if raw_symbols:
            if not isinstance(raw_symbols, list):
                return Response(
                    {"detail": "`symbols` must be a list of {startLine, endLine} ranges."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if len(raw_symbols) > _MAX_SYMBOLS:
                # Each symbol expands to a multiIf branch; an unbounded list would inflate the generated
                # SQL past ClickHouse's parse limits before any row cap applies.
                return Response(
                    {"detail": f"At most {_MAX_SYMBOLS} symbols may be requested at once."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                symbols = [self.get_model(s, SourceSymbol) for s in raw_symbols]
            except (ValidationError, ValueError, ParseError):
                return Response(
                    {"detail": "Each symbol must be an object with integer `startLine` and `endLine`."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if any(symbol.startLine > symbol.endLine for symbol in symbols):
                # An inverted range matches no line, so the symbol would silently vanish from the results.
                return Response(
                    {"detail": "Each symbol's `startLine` must be <= `endLine`."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if len({symbol.startLine for symbol in symbols}) != len(symbols):
                # Rows are keyed by startLine; duplicates would silently merge into one row with one name.
                return Response(
                    {"detail": "Symbols must have distinct `startLine` values."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        date_range = self.get_model(
            normalize_tracing_date_range(query_data.get("dateRange"), default_date_from="-24h"), DateRange
        )

        response = run_symbol_stats_query(team=self.team, file_path=file_path, date_range=date_range, symbols=symbols)
        granularity = response.granularity.value

        report_user_action(
            request.user,
            "tracing symbol stats queried",
            {
                "symbol_count": len(symbols or []),
                "matched_count": len(response.results),
                "granularity": granularity,
            },
            team=self.team,
            request=request,
        )

        return Response(
            {"results": [row.model_dump() for row in response.results], "granularity": granularity},
            status=status.HTTP_200_OK,
        )

    @extend_schema(request=_TracingSparklineRequestSerializer)
    @action(detail=False, methods=["POST"], required_scopes=["tracing:read"])
    def sparkline(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = request.data.get("query", {})
        date_range = self.get_model(normalize_tracing_date_range(query_data.get("dateRange")), DateRange)

        try:
            filter_group = (
                self.get_model(self._normalize_filter_group(query_data["filterGroup"]), PropertyGroupFilter)
                if query_data.get("filterGroup")
                else None
            )
        except (ValidationError, ValueError, ParseError):
            filter_group = None

        spans_query = TraceSpansQuery(
            dateRange=date_range,
            serviceNames=query_data.get("serviceNames", None),
            statusCodes=query_data.get("statusCodes", None),
            filterGroup=filter_group,
            rootSpans=query_data.get("rootSpans", False),
        )

        runner = TraceSpansSparklineQueryRunner(spans_query, self.team)
        response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)

        return Response({"results": response.results}, status=status.HTTP_200_OK)

    @extend_schema(request=_TracingDurationHistogramRequestSerializer)
    @action(detail=False, methods=["POST"], url_path="duration-histogram", required_scopes=["tracing:read"])
    def duration_histogram(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = request.data.get("query", {})
        date_range = self.get_model(normalize_tracing_date_range(query_data.get("dateRange")), DateRange)

        try:
            filter_group = (
                self.get_model(self._normalize_filter_group(query_data["filterGroup"]), PropertyGroupFilter)
                if query_data.get("filterGroup")
                else None
            )
        except (ValidationError, ValueError, ParseError):
            filter_group = None

        response = run_duration_histogram_query(
            team=self.team,
            date_range=date_range,
            service_names=query_data.get("serviceNames", None),
            status_codes=query_data.get("statusCodes", None),
            filter_group=filter_group,
            root_spans=query_data.get("rootSpans", True),
        )

        return Response({"results": response.results}, status=status.HTTP_200_OK)

    @extend_schema(request=_TracingAggregationRequestSerializer)
    @action(detail=False, methods=["POST"], url_path="aggregate", required_scopes=["tracing:read"])
    def aggregate(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = request.data.get("query", {}) or {}
        date_range = self.get_model(normalize_tracing_date_range(query_data.get("dateRange")), DateRange)

        try:
            filter_group = (
                self.get_model(self._normalize_filter_group(query_data["filterGroup"]), PropertyGroupFilter)
                if query_data.get("filterGroup")
                else None
            )
        except (ValidationError, ValueError, ParseError):
            filter_group = None

        compare_filter: CompareFilter | None = None
        compare_data = query_data.get("compareFilter")
        if compare_data:
            try:
                compare_filter = self.get_model(compare_data, CompareFilter)
            except (ValidationError, ValueError, ParseError):
                compare_filter = None

        response = run_aggregation_query(
            team=self.team,
            date_range=date_range,
            compare_filter=compare_filter,
            filter_group=filter_group,
            service_names=query_data.get("serviceNames", None),
        )

        return Response(
            {
                "results": [row.model_dump() for row in response.results],
                "compare": [row.model_dump() for row in (response.compare or [])] if response.compare else None,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(request=_TracingTreeRequestSerializer)
    @action(detail=False, methods=["POST"], url_path="tree", required_scopes=["tracing:read"])
    def tree(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = request.data.get("query", {}) or {}
        span_name = query_data.get("spanName")
        if not span_name or not isinstance(span_name, str):
            return Response(
                {"detail": "`spanName` is required for tree aggregation queries."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service_name = query_data.get("serviceName")
        if not service_name or not isinstance(service_name, str):
            return Response(
                {"detail": "`serviceName` is required for tree aggregation queries."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        date_range = self.get_model(normalize_tracing_date_range(query_data.get("dateRange")), DateRange)

        try:
            filter_group = (
                self.get_model(self._normalize_filter_group(query_data["filterGroup"]), PropertyGroupFilter)
                if query_data.get("filterGroup")
                else None
            )
        except (ValidationError, ValueError, ParseError):
            filter_group = None

        compare_filter: CompareFilter | None = None
        compare_data = query_data.get("compareFilter")
        if compare_data:
            try:
                compare_filter = self.get_model(compare_data, CompareFilter)
            except (ValidationError, ValueError, ParseError):
                compare_filter = None

        response = run_tree_query(
            team=self.team,
            date_range=date_range,
            span_name=span_name,
            service_name=service_name,
            compare_filter=compare_filter,
            filter_group=filter_group,
            service_names=query_data.get("serviceNames", None),
        )

        return Response(
            {
                "results": [row.model_dump() for row in response.results],
                "compare": [row.model_dump() for row in (response.compare or [])] if response.compare else None,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(request=_TracingAttributeBreakdownRequestSerializer)
    @action(detail=False, methods=["POST"], url_path="attribute-breakdown", required_scopes=["tracing:read"])
    def attribute_breakdown(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = request.data.get("query", {}) or {}

        breakdown_key = query_data.get("breakdownKey")
        if not breakdown_key or not isinstance(breakdown_key, str):
            return Response(
                {"detail": "`breakdownKey` is required for attribute breakdown queries."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            breakdown_type = TraceSpanBreakdownType(query_data.get("breakdownType") or "")
        except ValueError:
            return Response(
                {"detail": '`breakdownType` must be "span", "span_attribute" or "span_resource_attribute".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if breakdown_type == TraceSpanBreakdownType.SPAN and breakdown_key not in FACET_COLUMNS:
            return Response(
                {"detail": f"`breakdownKey` for a span column breakdown must be one of: {sorted(FACET_COLUMNS)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        order_by: TraceSpanBreakdownOrderBy | None = None
        if query_data.get("orderBy"):
            try:
                order_by = TraceSpanBreakdownOrderBy(query_data["orderBy"])
            except ValueError:
                return Response(
                    {"detail": '`orderBy` must be "count" or "error_count".'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        date_range = self.get_model(normalize_tracing_date_range(query_data.get("dateRange")), DateRange)

        try:
            filter_group = (
                self.get_model(self._normalize_filter_group(query_data["filterGroup"]), PropertyGroupFilter)
                if query_data.get("filterGroup")
                else None
            )
        except (ValidationError, ValueError, ParseError):
            filter_group = None

        compare_filter: CompareFilter | None = None
        compare_data = query_data.get("compareFilter")
        if compare_data:
            try:
                compare_filter = self.get_model(compare_data, CompareFilter)
            except (ValidationError, ValueError, ParseError):
                compare_filter = None

        response = run_attribute_breakdown_query(
            team=self.team,
            date_range=date_range,
            breakdown_key=breakdown_key,
            breakdown_type=breakdown_type,
            order_by=order_by,
            compare_filter=compare_filter,
            filter_group=filter_group,
            service_names=query_data.get("serviceNames", None),
            exclude_breakdown_filter=bool(query_data.get("excludeBreakdownFilter")),
        )

        return Response(
            {
                "results": [row.model_dump() for row in response.results],
                "compare": [row.model_dump() for row in (response.compare or [])] if response.compare else None,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(request=_TracingTraceRequestSerializer)
    @action(
        detail=False, methods=["POST"], url_path="trace/(?P<trace_id>[a-zA-Z0-9]+)", required_scopes=["tracing:read"]
    )
    def trace(self, request: Request, trace_id: str, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = request.data or {}
        date_range = self.get_model(
            normalize_tracing_date_range(query_data.get("dateRange"), default_date_from="-24h"), DateRange
        )
        try:
            # verify the trace_id is valid
            bytes.fromhex(trace_id)
        except ValueError:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        try:
            filter_group = (
                self.get_model(query_data["filterGroup"], PropertyGroupFilter)
                if query_data.get("filterGroup")
                else None
            )
        except (ValidationError, ValueError, ParseError):
            filter_group = None

        offset = max(int(query_data.get("offset") or 0), 0)

        # The waterfall loads a trace one page at a time, earliest spans first, with infinite scroll
        # fetching the next page. Order by start time ASC so a page is the first N spans by start
        # time; fetch one extra to detect whether more pages remain.
        spans_query = TraceSpansQuery(
            dateRange=date_range,
            traceId=trace_id,
            serviceNames=query_data.get("serviceNames", None),
            statusCodes=query_data.get("statusCodes", None),
            filterGroup=filter_group,
            orderBy="timestamp",
            orderDirection="ASC",
            limit=1,
            offset=offset,
            prefetchSpans=TRACE_SPANS_PAGE_SIZE + 1,
            rootSpans=False,
            excludeAttributes=query_data.get("excludeAttributes", False),
        )

        runner = TraceSpansQueryRunner(spans_query, self.team)
        response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)

        all_results = list(response.results) if isinstance(response.results, list) else []
        has_more = len(all_results) > TRACE_SPANS_PAGE_SIZE
        results = all_results[:TRACE_SPANS_PAGE_SIZE]

        # Self-time needs a span's children present. On a paged (truncated) trace it overstates for
        # spans whose children fall on a later page — an accepted bound, same as the prior 2000 cap.
        annotate_self_time(results)

        return Response(
            {
                "results": results,
                "hasMore": has_more,
                "nextOffset": offset + len(results) if has_more else None,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        parameters=[_TracingAttributesQuerySerializer],
        responses={200: _TracingAttributesResponseSerializer},
    )
    @action(detail=False, methods=["get"], required_scopes=["tracing:read"])
    def attributes(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        search = request.GET.get("search", "")
        search_values = request.GET.get("search_values", "false").lower() == "true"
        limit = int(request.GET.get("limit", "100"))
        offset = int(request.GET.get("offset", "0"))

        try:
            raw_date_range = json.loads(request.GET.get("dateRange", "{}"))
        except json.JSONDecodeError:
            raw_date_range = {}
        date_range = self.get_model(normalize_tracing_date_range(raw_date_range), DateRange)

        attribute_type = request.GET.get("attribute_type", "span_attribute")
        if attribute_type not in ("span_attribute", "span_resource_attribute"):
            attribute_type = "span_attribute"

        results, count = run_attribute_names_query(
            team=self.team,
            date_range=date_range,
            attribute_type=attribute_type,
            search=search,
            search_values=search_values,
            limit=limit,
            offset=offset,
        )

        return Response({"results": results, "count": count}, status=status.HTTP_200_OK)

    @extend_schema(parameters=[_TracingValuesQuerySerializer])
    @action(detail=False, methods=["GET"], required_scopes=["tracing:read"])
    def values(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        attribute_key = request.GET.get("key", "")
        if not attribute_key:
            return Response({"error": "key is required"}, status=status.HTTP_400_BAD_REQUEST)

        search = request.GET.get("value", "")
        limit = int(request.GET.get("limit", "100"))
        offset = int(request.GET.get("offset", "0"))

        try:
            raw_date_range = json.loads(request.GET.get("dateRange", "{}"))
        except json.JSONDecodeError:
            raw_date_range = {}
        date_range = self.get_model(normalize_tracing_date_range(raw_date_range), DateRange)

        attribute_type = request.GET.get("attribute_type", "span_attribute")
        if attribute_type not in ("span", "span_attribute", "span_resource_attribute"):
            attribute_type = "span_attribute"

        results = run_attribute_values_query(
            team=self.team,
            date_range=date_range,
            attribute_type=attribute_type,
            attribute_key=attribute_key,
            search=search,
            limit=limit,
            offset=offset,
        )

        return Response({"results": results}, status=status.HTTP_200_OK)
