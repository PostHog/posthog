import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets

from posthog.schema import ProductKey

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.models import ErrorTrackingIssueFingerprintV2

logger = structlog.get_logger(__name__)


class ErrorTrackingFingerprintSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingIssueFingerprintV2
        fields = ["fingerprint", "issue_id", "created_at"]


@extend_schema(tags=[ProductKey.ERROR_TRACKING])
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
