from django.apps import apps

from rest_framework import viewsets

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.presentation.serializers import (
    ErrorTrackingExternalReferenceSerializer,
    ErrorTrackingFingerprintSerializer,
)

ErrorTrackingExternalReference = apps.get_model("error_tracking", "ErrorTrackingExternalReference")
ErrorTrackingIssueFingerprintV2 = apps.get_model("error_tracking", "ErrorTrackingIssueFingerprintV2")


class ErrorTrackingFingerprintViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ReadOnlyModelViewSet):
    scope_object = "error_tracking"
    queryset = ErrorTrackingIssueFingerprintV2.objects.all()
    serializer_class = ErrorTrackingFingerprintSerializer

    def safely_get_queryset(self, queryset):
        params = self.request.GET.dict()
        queryset = queryset.filter(team_id=self.team.id)
        if params.get("issue_id"):
            queryset = queryset.filter(issue_id=params["issue_id"])
        return queryset


class ErrorTrackingExternalReferenceViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingExternalReference.objects.all()
    serializer_class = ErrorTrackingExternalReferenceSerializer
