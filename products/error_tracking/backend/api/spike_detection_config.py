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
    snooze_duration_minutes = serializers.IntegerField(
        min_value=1,
        help_text="Time to wait before alerting again for the same issue after a spike is detected.",
    )
    multiplier = serializers.IntegerField(
        min_value=1,
        help_text="The factor by which the current exception count must exceed the baseline to be considered a spike.",
    )
    threshold = serializers.IntegerField(
        min_value=1,
        help_text="The minimum number of exceptions required in a 5-minute window before a spike can be detected.",
    )

    class Meta:
        model = ErrorTrackingSpikeDetectionConfig
        fields = ["snooze_duration_minutes", "multiplier", "threshold"]


@extend_schema(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingSpikeDetectionConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "error_tracking"

    def _get_or_create_config(self):
        config, _ = ErrorTrackingSpikeDetectionConfig.objects.get_or_create(team=self.team)
        return config

    @extend_schema(responses={200: ErrorTrackingSpikeDetectionConfigSerializer})
    def list(self, request, *args, **kwargs):
        config = self._get_or_create_config()
        serializer = ErrorTrackingSpikeDetectionConfigSerializer(config)
        return Response(serializer.data)

    @extend_schema(
        request=ErrorTrackingSpikeDetectionConfigSerializer,
        responses={200: ErrorTrackingSpikeDetectionConfigSerializer},
    )
    @action(detail=False, methods=["patch"])
    def update_config(self, request, *args, **kwargs):
        config = self._get_or_create_config()
        serializer = ErrorTrackingSpikeDetectionConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
