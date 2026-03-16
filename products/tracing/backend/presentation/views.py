"""
DRF views for tracing.

Responsibilities:
- Validate incoming JSON (via serializers)
- Convert JSON to frozen dataclasses
- Call facade methods (facade/api.py)
- Convert frozen dataclasses to JSON responses

No business logic here - that belongs in logic.py via the facade.
"""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

# TODO: Once real data replaces fixtures, call facade methods instead:
# from ..facade import api
from ..logic import generate_fixture_spans, generate_fixture_sparkline, get_fixture_trace_spans


class SpansViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    def list(self, request: Request, *args, **kwargs) -> Response:
        return Response({"results": generate_fixture_spans(limit=100)}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["GET"], url_path="trace/(?P<trace_id>[a-f0-9]+)")
    def trace(self, request: Request, trace_id: str, *args, **kwargs) -> Response:
        return Response({"results": get_fixture_trace_spans(trace_id)}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["GET"])
    def sparkline(self, request: Request, *args, **kwargs) -> Response:
        spans = generate_fixture_spans()
        return Response({"results": generate_fixture_sparkline(spans)}, status=status.HTTP_200_OK)
