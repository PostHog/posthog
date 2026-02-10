from django.db.models import QuerySet

import structlog
from rest_framework import serializers, viewsets
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.models import ErrorTrackingAutoCaptureControls

logger = structlog.get_logger(__name__)

DEFAULT_LIBRARY = ErrorTrackingAutoCaptureControls.Library.WEB


class ErrorTrackingAutoCaptureControlsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingAutoCaptureControls
        fields = [
            "id",
            "library",
            "match_type",
            "sample_rate",
            "linked_feature_flag",
            "event_triggers",
            "url_triggers",
            "url_blocklist",
        ]
        read_only_fields = ["library"]


class ErrorTrackingAutoCaptureControlsViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "error_tracking"
    queryset = ErrorTrackingAutoCaptureControls.objects.all()
    serializer_class = ErrorTrackingAutoCaptureControlsSerializer

    def _get_library(self) -> str:
        return self.request.query_params.get("library", DEFAULT_LIBRARY)

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team=self.team)

    def list(self, request, *args, **kwargs):
        library = self._get_library()
        try:
            controls = ErrorTrackingAutoCaptureControls.objects.get(team=self.team, library=library)
            serializer = self.get_serializer(controls)
            return Response(serializer.data)
        except ErrorTrackingAutoCaptureControls.DoesNotExist:
            return Response(None)

    def create(self, request, *args, **kwargs):
        library = self._get_library()
        # Check if controls already exist for this library
        if ErrorTrackingAutoCaptureControls.objects.filter(team=self.team, library=library).exists():
            controls = ErrorTrackingAutoCaptureControls.objects.get(team=self.team, library=library)
            serializer = self.get_serializer(controls)
            return Response(serializer.data)

        # Create new controls
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(team=self.team, library=library)
        return Response(serializer.data, status=201)
