from typing import cast

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models import User

from ..models.clustering_config import ClusteringConfig


class ClusteringConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClusteringConfig
        fields = [
            "event_filters",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "created_at",
            "updated_at",
        ]


class ClusteringConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Team-level clustering configuration (event filters for automated pipelines)."""

    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated]

    @monitor(feature=None, endpoint="llma_clustering_config_list", method="GET")
    def list(self, request: Request, **kwargs) -> Response:
        config, _ = ClusteringConfig.objects.get_or_create(team_id=self.team_id)
        serializer = ClusteringConfigSerializer(config)
        return Response(serializer.data)

    @action(detail=False, methods=["post"])
    @monitor(feature=None, endpoint="llma_clustering_config_set_event_filters", method="POST")
    def set_event_filters(self, request: Request, **kwargs) -> Response:
        event_filters = request.data.get("event_filters")

        if event_filters is None:
            return Response(
                {"detail": "event_filters is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(event_filters, list):
            return Response(
                {"detail": "event_filters must be a list."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        config, _ = ClusteringConfig.objects.get_or_create(team_id=self.team_id)
        config.event_filters = event_filters
        config.save(update_fields=["event_filters", "updated_at"])

        report_user_action(
            cast(User, request.user),
            "llma clustering config event filters set",
            {
                "filter_count": len(event_filters),
            },
            self.team,
        )

        serializer = ClusteringConfigSerializer(config)
        return Response(serializer.data)
