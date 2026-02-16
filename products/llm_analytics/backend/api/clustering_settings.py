"""API endpoint for managing per-team clustering trace filters."""

from typing import cast

from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.permissions import AccessControlPermission

from products.llm_analytics.backend.trace_filters import get_team_trace_filters, set_team_trace_filters


class ClusteringSettingsSerializer(serializers.Serializer):
    trace_filters = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        help_text="Property filters to scope which traces are included in clustering (PostHog standard format)",
    )


class LLMAnalyticsClusteringSettingsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """ViewSet for managing per-team clustering settings."""

    scope_object = "llm_analytics"
    permission_classes = [IsAuthenticated, AccessControlPermission]

    @monitor(feature=None, endpoint="llma_clustering_settings_list", method="GET")
    def list(self, request: Request, **kwargs) -> Response:
        trace_filters = get_team_trace_filters(self.team)
        serializer = ClusteringSettingsSerializer({"trace_filters": trace_filters})
        return Response(serializer.data)

    @monitor(feature=None, endpoint="llma_clustering_settings_update", method="POST")
    def create(self, request: Request, **kwargs) -> Response:
        serializer = ClusteringSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        trace_filters = serializer.validated_data["trace_filters"]
        set_team_trace_filters(self.team, trace_filters)

        report_user_action(
            cast(User, request.user),
            "llma clustering settings updated",
            {"trace_filters_count": len(trace_filters)},
            self.team,
        )

        return Response({"trace_filters": trace_filters}, status=status.HTTP_200_OK)
