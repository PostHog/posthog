from rest_framework import viewsets

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.models import ErrorTrackingExternalReference
from products.error_tracking.backend.presentation.serializers import ErrorTrackingExternalReferenceSerializer


class ErrorTrackingExternalReferenceViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingExternalReference.objects.all()
    serializer_class = ErrorTrackingExternalReferenceSerializer
