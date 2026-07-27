from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.facade import api as error_tracking_api


class ErrorTrackingSpikeDetectionConfigSerializer(serializers.Serializer):
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


class ErrorTrackingSpikeDetectionConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "error_tracking"

    @extend_schema(responses={200: ErrorTrackingSpikeDetectionConfigSerializer})
    def list(self, request, *args, **kwargs):
        config = error_tracking_api.get_spike_detection_config(self.team.id)
        return Response(ErrorTrackingSpikeDetectionConfigSerializer(config).data)

    @extend_schema(
        request=ErrorTrackingSpikeDetectionConfigSerializer,
        responses={200: ErrorTrackingSpikeDetectionConfigSerializer},
    )
    @action(detail=False, methods=["patch"])
    def update_config(self, request, *args, **kwargs):
        serializer = ErrorTrackingSpikeDetectionConfigSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        config = error_tracking_api.update_spike_detection_config(self.team.id, dict(serializer.validated_data))
        return Response(ErrorTrackingSpikeDetectionConfigSerializer(config).data, status=status.HTTP_200_OK)
