import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.models import ErrorTrackingRateLimitConfig

logger = structlog.get_logger(__name__)


class ErrorTrackingRateLimitConfigSerializer(serializers.ModelSerializer):
    rate_limit_per_hour = serializers.IntegerField(
        min_value=1,
        allow_null=True,
        required=False,
        help_text="Maximum number of exception events ingested per hour. Null disables the limit.",
    )

    class Meta:
        model = ErrorTrackingRateLimitConfig
        fields = ["rate_limit_per_hour"]


@extend_schema(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingRateLimitConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "error_tracking"

    def _get_or_create_config(self) -> ErrorTrackingRateLimitConfig:
        config, _ = ErrorTrackingRateLimitConfig.objects.get_or_create(team=self.team)
        return config

    @extend_schema(responses={200: ErrorTrackingRateLimitConfigSerializer})
    def list(self, request, *args, **kwargs):
        config = self._get_or_create_config()
        serializer = ErrorTrackingRateLimitConfigSerializer(config)
        return Response(serializer.data)

    @extend_schema(
        request=ErrorTrackingRateLimitConfigSerializer,
        responses={200: ErrorTrackingRateLimitConfigSerializer},
    )
    @action(detail=False, methods=["patch"])
    def update_config(self, request, *args, **kwargs):
        config = self._get_or_create_config()
        serializer = ErrorTrackingRateLimitConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
