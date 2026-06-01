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

from drf_spectacular.utils import extend_schema
from pydantic import ValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import (
    CachedTraceSpansQueryResponse,
    DateRange,
    ProductKey,
    PropertyGroupFilter,
    TraceSpansQuery,
    TraceSpansQueryResponse,
)

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.hogql_queries.utils.time_sliced_query import time_sliced_results

from ..logic import (
    TraceSpansQueryRunner,
    run_attribute_names_query,
    run_attribute_values_query,
    run_service_names_query,
)
from ..sparkline_query_runner import TraceSpansSparklineQueryRunner

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
        help_text='Attribute key. For type "span", use built-in fields (trace_id, span_id, duration, name, kind, status_code). For "span_attribute"/"span_resource_attribute", use the attribute key (e.g. "http.method").',
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
        help_text="Filter by HTTP status codes.",
    )
    orderBy = serializers.ChoiceField(
        choices=["latest", "earliest"],
        required=False,
        help_text="Order results by timestamp. Defaults to latest.",
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
        help_text="Pagination cursor from previous response.",
    )
    rootSpans = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Filter to root spans only. Defaults to true.",
    )
    prefetchSpans = serializers.IntegerField(
        required=False,
        help_text="Number of child spans to prefetch per trace (1-100).",
    )


class _TracingQueryRequestSerializer(serializers.Serializer):
    query = _TracingQueryBodySerializer(help_text="The tracing spans query to execute.")


class _TracingTraceRequestSerializer(serializers.Serializer):
    dateRange = _TracingDateRangeSerializer(
        required=False,
        help_text="Date range for the query. Defaults to last 24 hours.",
    )


class _TracingServiceNamesQuerySerializer(serializers.Serializer):
    search = serializers.CharField(required=False, help_text="Search filter for service names.")
    dateRange = serializers.CharField(
        required=False,
        help_text='JSON-encoded date range, e.g. \'{"date_from": "-1h"}\'.',
    )


class _TracingAttributesQuerySerializer(serializers.Serializer):
    search = serializers.CharField(required=False, help_text="Search filter for attribute names.")
    attribute_type = serializers.ChoiceField(
        choices=["span", "resource"],
        required=False,
        help_text='Type of attributes: "span" for span attributes, "resource" for resource attributes.',
    )
    limit = serializers.IntegerField(
        required=False, min_value=1, max_value=100, help_text="Max results (default: 100)."
    )
    offset = serializers.IntegerField(required=False, min_value=0, help_text="Pagination offset (default: 0).")


class _TracingValuesQuerySerializer(serializers.Serializer):
    key = serializers.CharField(help_text="The attribute key to get values for.")
    attribute_type = serializers.ChoiceField(
        choices=["span", "resource"],
        required=False,
        help_text='Type of attribute: "span" or "resource".',
    )
    value = serializers.CharField(required=False, help_text="Search filter for attribute values.")
    limit = serializers.IntegerField(
        required=False, min_value=1, max_value=100, help_text="Max results (default: 100)."
    )
    offset = serializers.IntegerField(required=False, min_value=0, help_text="Pagination offset (default: 0).")


@extend_schema(tags=["tracing"])
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
            date_range = self.get_model(json.loads(request.GET.get("dateRange", '{"date_from": "-1h"}')), DateRange)
        except (json.JSONDecodeError, Exception):
            date_range = DateRange(date_from="-1h")

        results = run_service_names_query(team=self.team, date_range=date_range, search=search)
        return Response({"results": results}, status=status.HTTP_200_OK)

    @extend_schema(request=_TracingQueryRequestSerializer)
    @action(detail=False, methods=["POST"], required_scopes=["tracing:read"])
    def query(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = request.data.get("query", {})

        after_cursor = query_data.get("after", None)
        date_range = self.get_model(query_data.get("dateRange", {"date_from": "-1h"}), DateRange)

        order_by = query_data.get("orderBy")
        if order_by not in ("earliest", "latest"):
            order_by = "latest"

        requested_limit = min(query_data.get("limit", 100), 1000)
        prefetch_spans = query_data.get("prefetchSpans", None)
        if prefetch_spans is not None:
            prefetch_spans = min(int(prefetch_spans), 100)

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
            filterGroup=filter_group,
            traceId=query_data.get("traceId", None),
            limit=requested_limit + 1,
            after=after_cursor,
            rootSpans=query_data.get("rootSpans", True),
            prefetchSpans=prefetch_spans,
        )

        def make_runner(dr: DateRange) -> TraceSpansQueryRunner:
            return TraceSpansQueryRunner(TraceSpansQuery(**{**spans_query.model_dump(), "dateRange": dr}), self.team)

        results = list(
            time_sliced_results(
                runner=TraceSpansQueryRunner(spans_query, self.team),
                order_by_earliest=order_by == "earliest",
                make_runner=make_runner,
            )
        )

        return Response(
            {
                "results": results,
                "hasMore": False,  # TODO: tricky with the traces query as we prefetch an unknown number of spans
                "nextCursor": None,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(request=_TracingQueryRequestSerializer)
    @action(detail=False, methods=["POST"], required_scopes=["tracing:read"])
    def sparkline(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = request.data.get("query", {})
        date_range = self.get_model(query_data.get("dateRange", {"date_from": "-1h"}), DateRange)

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
        )

        runner = TraceSpansSparklineQueryRunner(spans_query, self.team)
        response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)

        return Response({"results": response.results}, status=status.HTTP_200_OK)

    @extend_schema(request=_TracingTraceRequestSerializer)
    @action(
        detail=False, methods=["POST"], url_path="trace/(?P<trace_id>[a-zA-Z0-9]+)", required_scopes=["tracing:read"]
    )
    def trace(self, request: Request, trace_id: str, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = request.data or {}
        date_range = self.get_model(query_data.get("dateRange", {"date_from": "-24h"}), DateRange)
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

        spans_query = TraceSpansQuery(
            dateRange=date_range,
            traceId=trace_id,
            serviceNames=query_data.get("serviceNames", None),
            statusCodes=query_data.get("statusCodes", None),
            filterGroup=filter_group,
            limit=1000,
            prefetchSpans=2000,
            rootSpans=False,
        )

        runner = TraceSpansQueryRunner(spans_query, self.team)
        response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)

        return Response(
            {"results": response.results},
            status=status.HTTP_200_OK,
        )

    @extend_schema(parameters=[_TracingAttributesQuerySerializer])
    @action(detail=False, methods=["get"], required_scopes=["tracing:read"])
    def attributes(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        search = request.GET.get("search", "")
        limit = int(request.GET.get("limit", "100"))
        offset = int(request.GET.get("offset", "0"))

        try:
            date_range = self.get_model(json.loads(request.GET.get("dateRange", "{}")), DateRange)
        except (json.JSONDecodeError, ValidationError, ValueError):
            date_range = DateRange(date_from="-1h")

        attribute_type = request.GET.get("attribute_type", "span")
        if attribute_type not in ("span", "resource"):
            attribute_type = "span"

        results, count = run_attribute_names_query(
            team=self.team,
            date_range=date_range,
            attribute_type=attribute_type,
            search=search,
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
            date_range = self.get_model(json.loads(request.GET.get("dateRange", "{}")), DateRange)
        except (json.JSONDecodeError, ValidationError, ValueError):
            date_range = DateRange(date_from="-1h")

        attribute_type = request.GET.get("attribute_type", "span")
        if attribute_type not in ("span", "resource"):
            attribute_type = "span"

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
