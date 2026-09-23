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
from collections.abc import Callable

from django.db import models

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from pydantic import ValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError, PermissionDenied
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
from posthog.api.mixins import PydanticModelMixin, ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.errors import CHQueryErrorTooManyBytes
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.property.property import STRING_PREFIX_SUFFIX_OPERATORS

from ..facade.api import (
    FACET_COLUMNS,
    MAX_IDS_PER_LOOKUP,
    annotate_self_time,
    count_session_exceptions,
    count_span_exceptions,
    count_trace_exceptions,
    run_attribute_breakdown_query,
    run_count_query,
    run_duration_histogram_query,
    run_impact_query,
    run_latency_heatmap_query,
    run_symbol_stats_query,
)
from ..has_spans_query_runner import team_has_spans
from ..logic import (
    _ROW_LIMIT,
    DEFAULT_AGGREGATION_ROW_LIMIT,
    TraceSpansQueryRunner,
    run_aggregation_query,
    run_attribute_names_query,
    run_attribute_values_query,
    run_service_names_query,
    run_tree_query,
)
from ..sparkline_query_runner import TraceSpansSparklineQueryRunner
from .date_window import normalize_tracing_date_range


def _serialize_compare_rows(compare_rows: list | None) -> list[dict] | None:
    """Serialize comparison-window rows for a response.

    Preserves the difference between "comparison not requested" (`None`) and "comparison
    requested but the window matched no spans" (`[]`). Collapsing the empty case to null
    makes a successful comparison indistinguishable from one that never ran — the caller
    reads it as the comparison being silently ignored.
    """
    if compare_rows is None:
        return None
    return [row.model_dump() for row in compare_rows]


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
_SPAN_STRING_OPERATORS = [
    "exact",
    "is_not",
    "icontains",
    "not_icontains",
    *STRING_PREFIX_SUFFIX_OPERATORS,
    "regex",
    "not_regex",
]
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


# The UI sends the nested group its filter editor produces, while MCP sends a flat list that
# `_normalize_filter_group` wraps into the same shape. A contract naming only the flat list
# makes every UI caller cast its way past the generated type.
_SPAN_FILTER_GROUP_SCHEMA = {
    "oneOf": [
        {
            "type": "array",
            "items": {"$ref": "#/components/schemas/_SpanPropertyFilter"},
            "description": "A flat list of filters, combined with AND.",
        },
        {
            "type": "object",
            "description": "A nested group of filter groups, as the UI filter editor builds it.",
            "properties": {
                "type": {"type": "string", "enum": ["AND", "OR"], "description": "How the inner groups combine."},
                "values": {
                    "type": "array",
                    "description": "The inner filter groups.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["AND", "OR"],
                                "description": "How the filters in this group combine.",
                            },
                            "values": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/_SpanPropertyFilter"},
                                "description": "The property filters in this group.",
                            },
                        },
                        "required": ["type", "values"],
                    },
                },
            },
            "required": ["type", "values"],
        },
    ]
}


@extend_schema_field(_SPAN_FILTER_GROUP_SCHEMA)
class _SpanFilterGroupField(serializers.JSONField):
    """Documents both filter shapes the span actions accept.

    These body serializers only feed the OpenAPI spec, so the runtime field stays permissive and
    the decorator carries the contract.
    """


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


class _TracingLatencyHeatmapRequestSerializer(serializers.Serializer):
    query = _TracingDurationHistogramQueryBodySerializer(help_text="The latency-heatmap query to execute.")


class _TracingLatencyHeatmapCellSerializer(serializers.Serializer):
    time = serializers.CharField(help_text="ISO 8601 UTC start of the time bucket.")
    bucket_ns = serializers.IntegerField(
        help_text=(
            "Lower edge of the 1-2-5 series duration bucket in nanoseconds (1ms, 2ms, 5ms, 10ms, ...). "
            "0 on the sentinel row that enumerates a time bucket with no matching spans."
        ),
    )
    count = serializers.IntegerField(
        help_text=(
            "Traces in this cell, bucketed by root-span duration (the default, rootSpans=true). "
            "When rootSpans is false, every matching span is counted instead. 0 only on sentinel rows."
        ),
    )


class _TracingLatencyHeatmapResponseSerializer(serializers.Serializer):
    results = _TracingLatencyHeatmapCellSerializer(
        many=True,
        help_text=(
            "Sparse heatmap cells ordered by time then duration bucket. Every time bucket in the "
            "window appears in at least one row, so the full x axis can be derived from the response."
        ),
    )


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


def _error_count_rows(counts: dict[str, int], key: str) -> list[dict[str, object]]:
    return [{key: value, "exceptions": count} for value, count in counts.items()]


class _TracingErrorCountsRequestSerializer(serializers.Serializer):
    traceIds = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        max_length=MAX_IDS_PER_LOOKUP,
        help_text=(
            f"Hex trace IDs to count exceptions for, matched against the exception's `$trace_id` "
            f"property. Case insensitive. At most {MAX_IDS_PER_LOOKUP} per request."
        ),
    )
    spanIds = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        max_length=MAX_IDS_PER_LOOKUP,
        help_text=(
            f"Hex span IDs to count exceptions for, matched against the exception's `$span_id` "
            f"property. Only counted within the requested traces, so `traceIds` is required "
            f"alongside. At most {MAX_IDS_PER_LOOKUP} per request."
        ),
    )
    sessionIds = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        max_length=MAX_IDS_PER_LOOKUP,
        help_text=(
            f"Session IDs to count exceptions for. The fallback for exceptions that carry no "
            f"trace ID. At most {MAX_IDS_PER_LOOKUP} per request."
        ),
    )
    dateFrom = serializers.DateTimeField(help_text="Start of the window the exceptions must fall in. ISO 8601.")
    dateTo = serializers.DateTimeField(help_text="End of the window the exceptions must fall in. ISO 8601.")

    def validate(self, attrs: dict) -> dict:
        if not any(attrs.get(key) for key in ("traceIds", "spanIds", "sessionIds")):
            raise serializers.ValidationError("Pass at least one of traceIds, spanIds or sessionIds.")
        if attrs.get("spanIds") and not attrs.get("traceIds"):
            raise serializers.ValidationError("spanIds needs traceIds, because a span ID is only unique in its trace.")
        return attrs


class _TracingErrorCountSerializer(serializers.Serializer):
    exceptions = serializers.IntegerField(
        help_text="Exception events in the window that error tracking linked to an issue."
    )


class _TracingTraceErrorCountSerializer(_TracingErrorCountSerializer):
    trace_id = serializers.CharField(help_text="The trace the exceptions belong to, lowercase hex.")


class _TracingSpanErrorCountSerializer(_TracingErrorCountSerializer):
    span_id = serializers.CharField(help_text="The span the exceptions belong to, lowercase hex.")


class _TracingSessionErrorCountSerializer(_TracingErrorCountSerializer):
    session_id = serializers.CharField(help_text="The session the exceptions belong to.")


class _TracingErrorCountsResponseSerializer(serializers.Serializer):
    traceResults = _TracingTraceErrorCountSerializer(
        many=True,
        help_text="One entry per requested trace that had exceptions. Traces with none are omitted.",
    )
    spanResults = _TracingSpanErrorCountSerializer(
        many=True,
        help_text="One entry per requested span that had exceptions. Spans with none are omitted.",
    )
    sessionResults = _TracingSessionErrorCountSerializer(
        many=True,
        help_text="One entry per requested session that had exceptions. Sessions with none are omitted.",
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


class SpanPropertyType(models.TextChoices):
    SPAN = "span", "span"
    SPAN_ATTRIBUTE = "span_attribute", "span_attribute"
    SPAN_RESOURCE_ATTRIBUTE = "span_resource_attribute", "span_resource_attribute"


class _TracingValuesQuerySerializer(serializers.Serializer):
    key = serializers.CharField(help_text="The attribute key to get values for.")
    attribute_type = serializers.ChoiceField(
        choices=SpanPropertyType.choices,
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
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=_ROW_LIMIT,
        help_text=(
            f"Max rows to return, ordered by total_duration_nano DESC. Defaults to {DEFAULT_AGGREGATION_ROW_LIMIT}; "
            f"hard max {_ROW_LIMIT}. Keep this small to bound the response size — a high value on high-cardinality "
            "span names (e.g. untemplated URL paths) returns a very large payload. Prefer narrowing with "
            "`serviceNames`/`filterGroup` over raising the limit."
        ),
    )
    offset = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text=(
            "Row offset for pagination. Combine with `limit` and the `next_offset` returned in the response to page "
            "through results beyond the first page."
        ),
    )
    includeImpact = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Also return the sessions and people behind each operation. Off by default because it reads the span "
            "and resource attribute maps, which the rest of the aggregation never touches."
        ),
    )


class _TracingAggregationRequestSerializer(serializers.Serializer):
    query = _TracingAggregationQueryBodySerializer(help_text="The span aggregation query to execute.")


class _AggregatedSpanRowSerializer(serializers.Serializer):
    service_name = serializers.CharField(help_text="Service that emitted the spans in this group.")
    name = serializers.CharField(help_text="Span name (operation) for this group.")
    count = serializers.IntegerField(help_text="Number of spans matched in this group.")
    total_duration_nano = serializers.FloatField(help_text="Sum of span durations in nanoseconds.")
    avg_duration_nano = serializers.FloatField(help_text="Average span duration in nanoseconds.")
    p50_duration_nano = serializers.FloatField(help_text="Median span duration in nanoseconds.")
    p95_duration_nano = serializers.FloatField(help_text="95th percentile span duration in nanoseconds.")
    p99_duration_nano = serializers.FloatField(help_text="99th percentile span duration in nanoseconds.")
    p999_duration_nano = serializers.FloatField(help_text="99.9th percentile span duration in nanoseconds.")
    error_count = serializers.IntegerField(help_text="Spans with OTel status code Error (status_code = 2).")
    sessions = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "Estimated unique session IDs across this group's spans (HyperLogLog, about 1-2% error). "
            "Null unless the query set `includeImpact`."
        ),
    )
    users = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "Estimated unique person distinct IDs across this group's spans (HyperLogLog, about 1-2% error). "
            "Null unless the query set `includeImpact`."
        ),
    )
    spans_with_session_id = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "How many of this group's spans carry a session ID under the team's configured or conventional "
            "attribute keys. Null unless the query set `includeImpact`."
        ),
    )
    spans_with_distinct_id = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "How many of this group's spans carry a person distinct ID under the team's configured or conventional "
            "attribute keys. Null unless the query set `includeImpact`."
        ),
    )


class _TracingAggregationResponseSerializer(serializers.Serializer):
    results = _AggregatedSpanRowSerializer(
        many=True,
        help_text="One row per (service_name, name) group, ordered by total_duration_nano descending.",
    )
    compare = _AggregatedSpanRowSerializer(
        many=True,
        allow_null=True,
        help_text="Rows for the comparison window when compareFilter.compare is true, else null.",
    )
    has_more = serializers.BooleanField(
        help_text="True when more rows exist beyond this page — page further with `next_offset`, or narrow the query."
    )
    next_offset = serializers.IntegerField(
        allow_null=True,
        help_text="Offset to request the next page, or null when this is the last page.",
    )


class _TracingAttributeBreakdownQueryBodySerializer(serializers.Serializer):
    breakdownKey = serializers.CharField(
        required=True,
        help_text='Attribute key to group by (e.g. "server.address", "http.response.status_code"). Discover keys with apm-attributes-list. For the "span" breakdown type, must be one of the allowlisted top-level columns: "service_name", "status_code".',
    )
    breakdownType = serializers.ChoiceField(
        choices=SpanPropertyType.choices,
        help_text='Where the key lives: "span" for allowlisted top-level span columns, "span_attribute" for span-level attributes, "span_resource_attribute" for resource-level attributes.',
    )
    excludeBreakdownFilter = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Drop filters targeting the breakdown key itself (including serviceNames for a service_name breakdown), so a facet's value list stays complete while one of its values is selected.",
    )
    facetSearch = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Type-ahead filter over the breakdown field's own values (case-insensitive substring match). "
        "An empty string means no filter. Lets a facet's value search reach past the row limit.",
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


class _TracingAttributeBreakdownRowSerializer(serializers.Serializer):
    value = serializers.CharField(
        help_text="The attribute's value for this group. Spans without the attribute group under ''."
    )
    count = serializers.IntegerField(help_text="Number of matching spans with this value.")
    error_count = serializers.IntegerField(help_text="Number of matching error spans (status_code = 2).")
    p50_duration_nano = serializers.FloatField(help_text="Median span duration in nanoseconds.")
    p95_duration_nano = serializers.FloatField(help_text="95th percentile span duration in nanoseconds.")


class _TracingAttributeBreakdownResponseSerializer(serializers.Serializer):
    results = _TracingAttributeBreakdownRowSerializer(
        many=True,
        help_text="One row per distinct attribute value, ordered by the requested column descending.",
    )
    compare = _TracingAttributeBreakdownRowSerializer(
        many=True,
        allow_null=True,
        help_text="Rows for the comparison window when compareFilter.compare is true, else null.",
    )


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


class _SpanSerializer(serializers.Serializer):
    """One span row as the query and trace actions return it.

    The runner assembles these from HogQL result columns by position, so the key set is fixed even
    though the values come from a query. `trace_start` and `trace_duration` are the sort keys the
    trace list orders on, carried in the row rather than recomputed by the caller.
    """

    uuid = serializers.CharField(help_text="Span's own UUID.")
    trace_id = serializers.CharField(help_text="Trace this span belongs to.")
    span_id = serializers.CharField(help_text="Span's ID within the trace.")
    parent_span_id = serializers.CharField(help_text="Parent span's ID. Empty for a root span.")
    name = serializers.CharField(help_text="Span name, which is the operation it represents.")
    kind = serializers.IntegerField(help_text="OpenTelemetry span kind.")
    service_name = serializers.CharField(help_text="Service that emitted the span.")
    status_code = serializers.IntegerField(help_text="OpenTelemetry status code: 0 unset, 1 ok, 2 error.")
    timestamp = serializers.DateTimeField(help_text="When the span started.")
    end_time = serializers.DateTimeField(help_text="When the span ended.")
    duration_nano = serializers.FloatField(help_text="Span duration in nanoseconds.")
    is_root_span = serializers.BooleanField(help_text="Whether the span has no parent in the trace.")
    matched_filter = serializers.IntegerField(
        help_text=(
            "1 when this span matched the request's filters, 0 when it is included as context. The query "
            "selects it as an expression, so it arrives as a number rather than a boolean."
        )
    )
    trace_start = serializers.DateTimeField(help_text="Start of the whole trace, for ordering traces by recency.")
    trace_duration = serializers.FloatField(
        help_text="Duration of the whole trace in nanoseconds. Falls back to this span's duration."
    )
    attributes = serializers.DictField(
        child=serializers.CharField(),
        help_text="Span attributes. Keys are whatever the instrumentation set.",
    )
    resource_attributes = serializers.DictField(
        child=serializers.CharField(),
        help_text="Resource attributes of the emitting service. Keys are whatever the instrumentation set.",
    )


class _TraceSpanSerializer(_SpanSerializer):
    """A span in a single trace. The trace action adds self time, which the list does not compute."""

    self_time_nano = serializers.FloatField(
        help_text="Span duration minus the time spent in its children, in nanoseconds."
    )


class _TracingQueryResponseSerializer(serializers.Serializer):
    results = _SpanSerializer(many=True, help_text="Matching spans, ordered by the requested column.")
    hasMore = serializers.BooleanField(help_text="Whether a further page exists.")
    nextCursor = serializers.CharField(
        allow_null=True,
        help_text=(
            "Cursor for the next page, or null on the last page. Pass it back as the query's `after`. "
            "Always null when ordering by duration, which pages by offset instead."
        ),
    )


class _TracingTraceResponseSerializer(serializers.Serializer):
    results = _TraceSpanSerializer(many=True, help_text="Spans in the trace, earliest first.")
    hasMore = serializers.BooleanField(help_text="Whether a further page of spans exists.")
    nextOffset = serializers.IntegerField(
        allow_null=True, help_text="Offset for the next page, or null on the last page."
    )


class _TracingSparklineRowSerializer(serializers.Serializer):
    time = serializers.DateTimeField(help_text="Start of the time bucket.")
    service = serializers.CharField(help_text="Service the count belongs to.")
    count = serializers.IntegerField(help_text="Spans in this bucket for this service.")


class _TracingSparklineResponseSerializer(serializers.Serializer):
    results = _TracingSparklineRowSerializer(
        many=True, help_text="One row per time bucket and service, ordered by time."
    )


class _TracingDurationHistogramRowSerializer(serializers.Serializer):
    bucket_ns = serializers.IntegerField(help_text="Lower bound of the duration bucket in nanoseconds.")
    service = serializers.CharField(help_text="Service the count belongs to.")
    count = serializers.IntegerField(help_text="Spans in this bucket for this service.")


class _TracingDurationHistogramResponseSerializer(serializers.Serializer):
    results = _TracingDurationHistogramRowSerializer(many=True, help_text="One row per duration bucket and service.")


class _SpanTreeNodeSerializer(serializers.Serializer):
    """One node of the aggregated call tree. Mirrors `SpanTreeNode` in posthog.schema."""

    name = serializers.CharField(help_text="Span name for this node.")
    service_name = serializers.CharField(help_text="Service that emitted the spans.")
    parent_name = serializers.CharField(
        help_text="Parent node's span name. The literal `<ROOT>` for a root node, which is how a client finds the roots."
    )
    parent_service = serializers.CharField(help_text="Parent node's service. Empty string at the root.")
    count = serializers.IntegerField(help_text="Spans aggregated into this node.")
    error_count = serializers.IntegerField(help_text="How many of them reported an error status.")
    total_duration_nano = serializers.FloatField(help_text="Sum of durations in nanoseconds.")
    avg_duration_nano = serializers.FloatField(help_text="Mean duration in nanoseconds.")
    p50_duration_nano = serializers.FloatField(help_text="Median duration in nanoseconds.")
    p95_duration_nano = serializers.FloatField(help_text="95th percentile duration in nanoseconds.")
    p99_duration_nano = serializers.FloatField(help_text="99th percentile duration in nanoseconds.")
    p999_duration_nano = serializers.FloatField(help_text="99.9th percentile duration in nanoseconds.")
    avg_start_offset_nano = serializers.FloatField(
        help_text="Mean nanoseconds from the parent's start to this node's start. Zero at the root."
    )
    calls_per_parent_invocation = serializers.FloatField(
        allow_null=True, help_text="Mean calls per parent invocation. Null at the root."
    )


class _TracingTreeResponseSerializer(serializers.Serializer):
    results = _SpanTreeNodeSerializer(many=True, help_text="Call tree nodes for the requested window.")
    compare = _SpanTreeNodeSerializer(
        many=True,
        allow_null=True,
        help_text=(
            "Nodes for the comparison window when compareFilter.compare is true. Null when no comparison "
            "was requested, and an empty list when one was requested and matched no spans."
        ),
    )


class _TracingServiceNameSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Service name.")


class _TracingServiceNamesResponseSerializer(serializers.Serializer):
    results = _TracingServiceNameSerializer(many=True, help_text="Services that emitted spans in the window.")


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
    filterGroup = _SpanFilterGroupField(
        required=False,
        help_text="Property filters for the count. Either a flat list of filters or a nested filter group.",
    )


class _TracingCountRequestSerializer(serializers.Serializer):
    query = _TracingCountBodySerializer(help_text="The span count query to execute.")


class _TracingCountResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Number of spans matching the filters.")
    traceCount = serializers.IntegerField(
        help_text="Number of distinct traces whose root span matches the filters — the trace count shown in the Traces view."
    )


class _TracingImpactRequestSerializer(serializers.Serializer):
    query = _TracingCountBodySerializer(
        help_text="The impact query to execute. Takes the same filters as the count query."
    )


class _TracingImpactTopValueSerializer(serializers.Serializer):
    value = serializers.CharField(help_text="The session ID or person distinct ID.")
    count = serializers.IntegerField(
        help_text="Approximate number of matching spans that carry this value (topK estimate)."
    )


class _TracingImpactResponseSerializer(serializers.Serializer):
    total = serializers.IntegerField(help_text="Number of spans matching the filters.")
    spansWithSessionId = serializers.IntegerField(
        help_text=(
            "How many of the matching spans carry a session ID under the team's configured or conventional "
            "attribute keys."
        )
    )
    sessions = serializers.IntegerField(
        help_text="Estimated number of unique session IDs across the matching spans (HyperLogLog, about 1-2% error)."
    )
    spansWithDistinctId = serializers.IntegerField(
        help_text=(
            "How many of the matching spans carry a person distinct ID under the team's configured or conventional "
            "attribute keys."
        )
    )
    users = serializers.IntegerField(
        help_text="Estimated number of unique distinct IDs across the matching spans (HyperLogLog, about 1-2% error)."
    )
    topSessions = _TracingImpactTopValueSerializer(
        many=True,
        help_text="Top session IDs on the matching spans, ordered by span count descending (topK, at most 5).",
    )
    topUsers = _TracingImpactTopValueSerializer(
        many=True,
        help_text="Top person distinct IDs on the matching spans, ordered by span count descending (topK, at most 5).",
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

    @staticmethod
    def _query_body(data: object) -> dict:
        """The `query` object every span action reads its filters from, given a parsed body.

        `request.data` is whatever JSON the client sent, so without this a string or an array
        reaches the `query_data.get(...)` calls in each action and raises `AttributeError`,
        which turns a malformed request into a 500.
        """
        if not isinstance(data, dict):
            raise ParseError("Request body must be an object.")
        query_data = data.get("query") or {}
        if not isinstance(query_data, dict):
            raise ParseError("`query` must be an object.")
        return query_data

    @staticmethod
    def _parse_positive_int(value: object, default: int, *, minimum: int) -> int:
        """Coerce an untrusted JSON value to an int no smaller than `minimum`, falling back to `default`."""
        if not isinstance(value, int | str | float) or isinstance(value, bool):
            return default
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(minimum, parsed)

    def _report_usage(self, request: Request, event: str, properties: dict) -> None:
        # Usage telemetry must never turn a successful read into a 5xx, so swallow and record any failure.
        try:
            report_user_action(request.user, event, properties, team=self.team, request=request)
        except Exception as e:
            capture_exception(e)

    def _parse_compare_filter(self, query_data: dict) -> CompareFilter | None:
        """Parse an optional comparison window from the request body.

        A malformed ``compareFilter`` raises (surfacing a 400), rather than being swallowed
        into ``None`` — otherwise a caller that asked for a comparison gets a successful
        response with ``compare: null`` and no hint that its filter was rejected.
        """
        compare_data = query_data.get("compareFilter")
        if not compare_data:
            return None
        return self.get_model(compare_data, CompareFilter)

    @validated_request(
        _TracingErrorCountsRequestSerializer,
        responses={200: OpenApiResponse(response=_TracingErrorCountsResponseSerializer)},
    )
    # Both scopes: the response is Error Tracking data, so a token scoped to tracing alone must
    # not reach it. Scopes gate the token; the access-control check below gates the user.
    @action(
        detail=False,
        methods=["POST"],
        url_path="error-counts",
        required_scopes=["tracing:read", "error_tracking:read"],
    )
    def error_counts(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        """Count the exceptions the spans in view hit, by trace, by span and by session, for the
        span list's error badges.

        A caller asks about the id kinds it has, and each kind is a separate lookup.
        """
        if not self.user_access_control.check_access_level_for_resource("error_tracking", "viewer"):
            raise PermissionDenied("You do not have access to error tracking.")

        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        data = request.validated_data
        trace_ids = data.get("traceIds") or []
        span_ids = data.get("spanIds") or []
        session_ids = data.get("sessionIds") or []
        window = {"date_from": data["dateFrom"], "date_to": data["dateTo"]}

        # Through the response serializer, not a bare dict: `api-response-must-match-schema` keeps
        # the wire shape tied to the declaration the generated types are built from.
        response = _TracingErrorCountsResponseSerializer(
            instance={
                "traceResults": _error_count_rows(
                    count_trace_exceptions(team=self.team, trace_ids=trace_ids, **window), "trace_id"
                ),
                "spanResults": _error_count_rows(
                    count_span_exceptions(team=self.team, span_ids=span_ids, trace_ids=trace_ids, **window), "span_id"
                ),
                "sessionResults": _error_count_rows(
                    count_session_exceptions(team=self.team, session_ids=session_ids, **window), "session_id"
                ),
            }
        )
        return Response(response.data, status=status.HTTP_200_OK)

    @extend_schema(
        parameters=[_TracingServiceNamesQuerySerializer],
        responses={200: _TracingServiceNamesResponseSerializer},
    )
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

    @extend_schema(
        request=_TracingQueryRequestSerializer,
        responses={200: _TracingQueryResponseSerializer},
    )
    @action(detail=False, methods=["POST"], required_scopes=["tracing:read"])
    def query(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = self._query_body(request.data)

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

    def _run_scalar_span_query(
        self,
        request: Request,
        runner: Callable[..., TraceSpansQueryResponse | CachedTraceSpansQueryResponse],
        *,
        event_name: str,
    ) -> Response:
        """Run one of the single-row span aggregates that sit beside the list, over the shared
        `_TracingCountBodySerializer` filters.

        These run on every filter change, so an over-wide window returns an actionable 400
        rather than an opaque 500.
        """
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = self._query_body(request.data)

        date_range = self.get_model(normalize_tracing_date_range(query_data.get("dateRange")), DateRange)
        filter_group = (
            self.get_model(self._normalize_filter_group(query_data.get("filterGroup")), PropertyGroupFilter)
            if query_data.get("filterGroup")
            else None
        )

        try:
            response = runner(
                team=self.team,
                date_range=date_range,
                service_names=query_data.get("serviceNames", None),
                status_codes=query_data.get("statusCodes", None),
                filter_group=filter_group,
            )
        except CHQueryErrorTooManyBytes:
            return Response(
                {
                    "detail": (
                        "This query scans too much data. Narrow the date range or add serviceNames, "
                        "statusCodes, or filterGroup filters, then retry."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        self._report_usage(
            request,
            event_name,
            {
                "has_filter_group": bool(query_data.get("filterGroup")),
                "service_names_count": len(query_data.get("serviceNames") or []),
                "status_codes_count": len(query_data.get("statusCodes") or []),
            },
        )

        return Response(response.results, status=status.HTTP_200_OK)

    @extend_schema(request=_TracingCountRequestSerializer, responses={200: _TracingCountResponseSerializer})
    @action(detail=False, methods=["POST"], required_scopes=["tracing:read"])
    def count(self, request: Request, *args, **kwargs) -> Response:
        return self._run_scalar_span_query(request, run_count_query, event_name="tracing count queried")

    @extend_schema(request=_TracingImpactRequestSerializer, responses={200: _TracingImpactResponseSerializer})
    @action(detail=False, methods=["POST"], required_scopes=["tracing:read"])
    def impact(self, request: Request, *args, **kwargs) -> Response:
        return self._run_scalar_span_query(request, run_impact_query, event_name="tracing impact queried")

    @extend_schema(request=_SymbolStatsRequestSerializer, responses={200: _SymbolStatsResponseSerializer})
    @action(detail=False, methods=["POST"], url_path="symbol-stats", required_scopes=["tracing:read"])
    def symbol_stats(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = self._query_body(request.data)

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

    @extend_schema(
        request=_TracingSparklineRequestSerializer,
        responses={200: _TracingSparklineResponseSerializer},
    )
    @action(detail=False, methods=["POST"], required_scopes=["tracing:read"])
    def sparkline(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = self._query_body(request.data)
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

    @extend_schema(
        request=_TracingDurationHistogramRequestSerializer,
        responses={200: _TracingDurationHistogramResponseSerializer},
    )
    @action(detail=False, methods=["POST"], url_path="duration-histogram", required_scopes=["tracing:read"])
    def duration_histogram(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = self._query_body(request.data)
        date_range = self.get_model(normalize_tracing_date_range(query_data.get("dateRange")), DateRange)

        try:
            filter_group = (
                self.get_model(self._normalize_filter_group(query_data["filterGroup"]), PropertyGroupFilter)
                if query_data.get("filterGroup")
                else None
            )
        except (ValidationError, ValueError, ParseError):
            filter_group = None

        root_spans = query_data.get("rootSpans", True)
        response = run_duration_histogram_query(
            team=self.team,
            date_range=date_range,
            service_names=query_data.get("serviceNames", None),
            status_codes=query_data.get("statusCodes", None),
            filter_group=filter_group,
            root_spans=root_spans,
        )

        self._report_usage(
            request,
            "tracing duration histogram queried",
            {
                "buckets_count": len(response.results),
                "root_spans": root_spans,
                "has_filter_group": bool(query_data.get("filterGroup")),
                "service_names_count": len(query_data.get("serviceNames") or []),
                "status_codes_count": len(query_data.get("statusCodes") or []),
            },
        )

        return Response({"results": response.results}, status=status.HTTP_200_OK)

    @extend_schema(
        request=_TracingLatencyHeatmapRequestSerializer,
        responses={200: _TracingLatencyHeatmapResponseSerializer},
    )
    @action(detail=False, methods=["POST"], url_path="latency-heatmap", required_scopes=["tracing:read"])
    def latency_heatmap(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = self._query_body(request.data)
        date_range = self.get_model(normalize_tracing_date_range(query_data.get("dateRange")), DateRange)

        try:
            filter_group = (
                self.get_model(self._normalize_filter_group(query_data["filterGroup"]), PropertyGroupFilter)
                if query_data.get("filterGroup")
                else None
            )
        except (ValidationError, ValueError, ParseError):
            filter_group = None

        response = run_latency_heatmap_query(
            team=self.team,
            date_range=date_range,
            service_names=query_data.get("serviceNames", None),
            status_codes=query_data.get("statusCodes", None),
            filter_group=filter_group,
            root_spans=query_data.get("rootSpans", True),
        )

        return Response({"results": response.results}, status=status.HTTP_200_OK)

    @extend_schema(request=_TracingAggregationRequestSerializer, responses={200: _TracingAggregationResponseSerializer})
    @action(detail=False, methods=["POST"], url_path="aggregate", required_scopes=["tracing:read"])
    def aggregate(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = self._query_body(request.data)
        date_range = self.get_model(normalize_tracing_date_range(query_data.get("dateRange")), DateRange)

        try:
            filter_group = (
                self.get_model(self._normalize_filter_group(query_data["filterGroup"]), PropertyGroupFilter)
                if query_data.get("filterGroup")
                else None
            )
        except (ValidationError, ValueError, ParseError):
            filter_group = None

        compare_filter = self._parse_compare_filter(query_data)

        # Bound the payload: default to a conservative page so agent/MCP callers don't pull the
        # full high-cardinality tail. Callers opt into more via `limit`/`offset`.
        limit = self._parse_positive_int(query_data.get("limit"), DEFAULT_AGGREGATION_ROW_LIMIT, minimum=1)
        limit = min(limit, _ROW_LIMIT)
        offset = self._parse_positive_int(query_data.get("offset"), 0, minimum=0)

        # Over-fetch one row so we can report `has_more` without a separate count query.
        response = run_aggregation_query(
            team=self.team,
            date_range=date_range,
            compare_filter=compare_filter,
            filter_group=filter_group,
            service_names=query_data.get("serviceNames", None),
            limit=min(limit + 1, _ROW_LIMIT),
            offset=offset,
            include_impact=bool(query_data.get("includeImpact")),
        )

        results = list(response.results)
        has_more = len(results) > limit
        results = results[:limit]
        # `None` when no comparison was requested, `[]` when it ran but matched no spans — keep them
        # distinct so an empty baseline isn't reported as "comparison ignored".
        compare_rows = list(response.compare)[:limit] if response.compare is not None else None

        self._report_usage(
            request,
            "tracing aggregation queried",
            {
                "results_count": len(results),
                "has_more": has_more,
                "limit": limit,
                "offset": offset,
                "has_compare": bool(query_data.get("compareFilter")),
                "has_filter_group": bool(query_data.get("filterGroup")),
                "service_names_count": len(query_data.get("serviceNames") or []),
                "include_impact": bool(query_data.get("includeImpact")),
            },
        )

        return Response(
            {
                "results": [row.model_dump() for row in results],
                "compare": _serialize_compare_rows(compare_rows),
                "has_more": has_more,
                "next_offset": offset + limit if has_more else None,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        request=_TracingTreeRequestSerializer,
        responses={200: _TracingTreeResponseSerializer},
    )
    @action(detail=False, methods=["POST"], url_path="tree", required_scopes=["tracing:read"])
    def tree(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = self._query_body(request.data)
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

        compare_filter = self._parse_compare_filter(query_data)

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
                "compare": _serialize_compare_rows(response.compare),
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        request=_TracingAttributeBreakdownRequestSerializer,
        responses={200: _TracingAttributeBreakdownResponseSerializer},
    )
    @action(detail=False, methods=["POST"], url_path="attribute-breakdown", required_scopes=["tracing:read"])
    def attribute_breakdown(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = self._query_body(request.data)

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

        compare_filter = self._parse_compare_filter(query_data)

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
            facet_search=query_data.get("facetSearch") or None,
        )

        return Response(
            {
                "results": [row.model_dump() for row in response.results],
                "compare": _serialize_compare_rows(response.compare),
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        request=_TracingTraceRequestSerializer,
        responses={200: _TracingTraceResponseSerializer},
    )
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

        self._report_usage(
            request,
            "tracing trace fetched",
            {
                "spans_count": len(results),
                "has_more": has_more,
                "is_paginated": offset > 0,
                "has_filter_group": bool(query_data.get("filterGroup")),
            },
        )

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
