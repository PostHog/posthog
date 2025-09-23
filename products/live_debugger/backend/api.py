from django.db.models import QuerySet

from rest_framework import serializers, viewsets
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.auth import PersonalAPIKeyAuthentication, SessionAuthentication

from products.live_debugger.backend.models import LiveDebuggerBreakpoint


class LiveDebuggerBreakpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = LiveDebuggerBreakpoint
        fields = ["id", "filename", "line_number", "enabled", "condition", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def create(self, validated_data):
        validated_data["team"] = self.context["team"]
        return super().create(validated_data)


class LiveDebuggerBreakpointViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete breakpoints for live debugging.
    """

    scope_object = "query"  # Changed from "INTERNAL" to allow API access
    scope_object_read_actions = ["list", "retrieve", "active_breakpoints", "breakpoint_hits"]
    scope_object_write_actions = ["create", "update", "partial_update", "destroy"]
    queryset = LiveDebuggerBreakpoint.objects.all()
    serializer_class = LiveDebuggerBreakpointSerializer
    basename = "live_debugger_breakpoints"

    def safely_get_queryset(self, queryset) -> QuerySet:
        return queryset.order_by("-created_at")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["team"] = self.team
        return context

    @action(methods=["GET"], detail=False)
    def breakpoint_hits(self, request, *args, **kwargs) -> Response:
        """
        Get breakpoint hit events from ClickHouse.

        Query parameters:
        - breakpoint_id (optional): Filter hits for specific breakpoint
        - limit (default: 100): Number of hits to return
        - offset (default: 0): Pagination offset
        """
        breakpoint_id = request.GET.get("breakpoint_id")

        try:
            limit = int(request.GET.get("limit", 100))
            limit = min(limit, 1000)  # Cap at 1000 for performance
        except ValueError:
            limit = 100

        try:
            offset = int(request.GET.get("offset", 0))
        except ValueError:
            offset = 0

        # Get breakpoint hits from ClickHouse
        hits = LiveDebuggerBreakpoint.get_breakpoint_hits(
            team_id=self.team.pk, breakpoint_id=breakpoint_id, limit=limit, offset=offset
        )

        # Transform the data to match frontend expectations
        transformed_hits = []
        for hit in hits:
            transformed_hits.append(
                {
                    "id": hit["id"],
                    "lineNumber": hit["line_number"],
                    "functionName": hit["function_name"],
                    "timestamp": hit["timestamp"],
                    "variables": hit["locals"],
                    "stackTrace": hit["stack_trace"],
                    "breakpoint_id": hit["breakpoint_id"],
                    "filename": hit["filename"],
                }
            )

        return Response(
            {
                "results": transformed_hits,
                "count": len(transformed_hits),
                "has_more": len(hits) == limit,  # Indicates if there might be more results
            }
        )

    @action(
        methods=["GET"],
        detail=False,
        authentication_classes=[PersonalAPIKeyAuthentication, SessionAuthentication],
        url_path="active",
    )
    def active_breakpoints(self, request, *args, **kwargs) -> Response:
        """
        External API endpoint for client applications to fetch active breakpoints using API key.

        This endpoint allows external client applications (like Python scripts, Node.js apps, etc.)
        to fetch the list of active breakpoints so they can instrument their code accordingly.

        Authentication: Requires a Personal API Key in the Authorization header:
        Authorization: Bearer <your-personal-api-key>

        Query parameters:
        - filename (optional): Filter breakpoints for specific file
        - enabled (default: true): Only return enabled breakpoints

        Response format optimized for client application consumption:
        {
            "breakpoints": [
                {
                    "id": "uuid",
                    "filename": "capture_event.py",
                    "line_number": 123,
                    "enabled": true,
                    "condition": "user_id == '12345'" // optional
                }
            ]
        }
        """
        # Filter by enabled breakpoints by default
        enabled_filter = request.GET.get("enabled", "true").lower() == "true"
        filename = request.GET.get("filename")

        queryset = self.get_queryset()

        if enabled_filter:
            queryset = queryset.filter(enabled=True)

        if filename:
            queryset = queryset.filter(filename=filename)

        breakpoints = queryset.values("id", "filename", "line_number", "enabled", "condition")

        return Response({"breakpoints": list(breakpoints)})
