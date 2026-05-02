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

from pydantic import ValidationError
from rest_framework import status, viewsets
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


class SpansViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer

    @action(detail=False, methods=["GET"], url_path="service-names")
    def service_names(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        search = request.GET.get("search", "")
        try:
            date_range = self.get_model(json.loads(request.GET.get("dateRange", '{"date_from": "-1h"}')), DateRange)
        except (json.JSONDecodeError, Exception):
            date_range = DateRange(date_from="-1h")

        results = run_service_names_query(team=self.team, date_range=date_range, search=search)
        return Response({"results": results}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["POST"])
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
            self.get_model(query_data.get("filterGroup"), PropertyGroupFilter)
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

    @action(detail=False, methods=["POST"])
    def sparkline(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        query_data = request.data.get("query", {})
        date_range = self.get_model(query_data.get("dateRange", {"date_from": "-1h"}), DateRange)

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
            serviceNames=query_data.get("serviceNames", None),
            statusCodes=query_data.get("statusCodes", None),
            filterGroup=filter_group,
        )

        runner = TraceSpansSparklineQueryRunner(spans_query, self.team)
        response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)

        return Response({"results": response.results}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["POST"], url_path="trace/(?P<trace_id>[a-zA-Z0-9]+)")
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

    @action(detail=False, methods=["get"])
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

    @action(detail=False, methods=["GET"])
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
