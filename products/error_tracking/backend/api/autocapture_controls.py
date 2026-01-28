from django.db.models import QuerySet

import structlog
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.models import ErrorTrackingAutoCaptureControls

logger = structlog.get_logger(__name__)


class ErrorTrackingAutoCaptureControlsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingAutoCaptureControls
        fields = [
            "id",
            "match_type",
            "sample_rate",
            "linked_feature_flag",
            "event_triggers",
            "url_triggers",
            "url_blocklist",
        ]


class ErrorTrackingAutoCaptureControlsViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "error_tracking"
    queryset = ErrorTrackingAutoCaptureControls.objects.all()
    serializer_class = ErrorTrackingAutoCaptureControlsSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team=self.team)

    def get_object(self):
        # For retrieve/update/delete, get the single controls object for this team
        return ErrorTrackingAutoCaptureControls.objects.get(team=self.team)

    def list(self, request, *args, **kwargs):
        # Return the controls if they exist, otherwise return null
        try:
            controls = ErrorTrackingAutoCaptureControls.objects.get(team=self.team)
            serializer = self.get_serializer(controls)
            return Response(serializer.data)
        except ErrorTrackingAutoCaptureControls.DoesNotExist:
            return Response(None)

    def create(self, request, *args, **kwargs):
        # Check if controls already exist
        if ErrorTrackingAutoCaptureControls.objects.filter(team=self.team).exists():
            controls = ErrorTrackingAutoCaptureControls.objects.get(team=self.team)
            serializer = self.get_serializer(controls)
            return Response(serializer.data)

        # Create new controls
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(team=self.team)
        return Response(serializer.data, status=201)

    @action(detail=False, methods=["delete"])
    def delete_controls(self, request, *args, **kwargs):
        """Delete the controls for this team."""
        try:
            controls = ErrorTrackingAutoCaptureControls.objects.get(team=self.team)
            controls.delete()
            return Response(status=204)
        except ErrorTrackingAutoCaptureControls.DoesNotExist:
            return Response(status=204)
