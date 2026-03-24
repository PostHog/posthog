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

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import CachedTraceSpansQueryResponse, DateRange, TraceSpansQuery, TraceSpansQueryResponse

from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.hogql_queries.query_runner import ExecutionMode

from ..logic import TraceSpansQueryRunner


class SpansViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    @action(detail=False, methods=["POST"])
    def query(self, request: Request, *args, **kwargs) -> Response:
        query_data = request.data.get("query", {})

        after_cursor = query_data.get("after", None)
        date_range = self.get_model(query_data.get("dateRange", {"date_from": "-1h"}), DateRange)

        order_by = query_data.get("orderBy")
        if order_by not in ("earliest", "latest"):
            order_by = "latest"

        requested_limit = min(query_data.get("limit", 100), 1000)
        spans_query = TraceSpansQuery(
            dateRange=date_range,
            serviceNames=query_data.get("serviceNames", None),
            statusCodes=query_data.get("statusCodes", None),
            orderBy=order_by,
            searchTerm=query_data.get("searchTerm", None),
            traceId=query_data.get("traceId", None),
            limit=requested_limit + 1,
            after=after_cursor,
            rootSpans=query_data.get("rootSpans", True),
        )

        runner = TraceSpansQueryRunner(spans_query, self.team)
        response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)

        results = response.results
        has_more = len(results) > requested_limit
        results = results[:requested_limit]

        next_cursor = None
        if has_more and results:
            last_result = results[-1]
            cursor_data = {
                "timestamp": last_result["timestamp"].isoformat(),
                "uuid": last_result["uuid"],
            }
            next_cursor = base64.b64encode(json.dumps(cursor_data).encode("utf-8")).decode("utf-8")

        return Response(
            {
                "results": results,
                "hasMore": has_more,
                "nextCursor": next_cursor,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["POST"], url_path="trace/(?P<trace_id>[a-zA-Z0-9]+)")
    def trace(self, request: Request, trace_id: str, *args, **kwargs) -> Response:
        query_data = request.data or {}
        date_range = self.get_model(query_data.get("dateRange", {"date_from": "-24h"}), DateRange)
        try:
            # verify the trace_id is valid
            base64.b64encode(bytes.fromhex(trace_id)).decode("ascii")
        except ValueError:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        spans_query = TraceSpansQuery(
            dateRange=date_range,
            traceId=trace_id,
            limit=1000,
            rootSpans=False,
        )

        runner = TraceSpansQueryRunner(spans_query, self.team)
        response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)

        return Response(
            {"results": response.results},
            status=status.HTTP_200_OK,
        )
