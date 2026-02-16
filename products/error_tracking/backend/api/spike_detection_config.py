import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.models import ErrorTrackingSpikeDetectionConfig

logger = structlog.get_logger(__name__)


class ErrorTrackingSpikeDetectionConfigSerializer(serializers.ModelSerializer):
    snooze_duration_minutes = serializers.IntegerField(min_value=1)
    multiplier = serializers.IntegerField(min_value=1)
    threshold = serializers.IntegerField(min_value=1)

    class Meta:
        model = ErrorTrackingSpikeDetectionConfig
        fields = ["snooze_duration_minutes", "multiplier", "threshold"]


@extend_schema(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingSpikeDetectionConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "error_tracking"

    def list(self, request, *args, **kwargs):
        try:
            config = ErrorTrackingSpikeDetectionConfig.objects.get(team=self.team)
        except ErrorTrackingSpikeDetectionConfig.DoesNotExist:
            return Response(None, status=status.HTTP_200_OK)
        serializer = ErrorTrackingSpikeDetectionConfigSerializer(config)
        return Response(serializer.data)

    @action(detail=False, methods=["post"])
    def enable(self, request, *args, **kwargs):
        config, created = ErrorTrackingSpikeDetectionConfig.objects.get_or_create(team=self.team)
        serializer = ErrorTrackingSpikeDetectionConfigSerializer(config)
        return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=False, methods=["patch"])
    def update_config(self, request, *args, **kwargs):
        try:
            config = ErrorTrackingSpikeDetectionConfig.objects.get(team=self.team)
        except ErrorTrackingSpikeDetectionConfig.DoesNotExist:
            return Response({"detail": "Spike detection is not enabled."}, status=status.HTTP_404_NOT_FOUND)
        serializer = ErrorTrackingSpikeDetectionConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
