from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.models import ErrorTrackingSettings


class ErrorTrackingSettingsSerializer(serializers.ModelSerializer):
    project_rate_limit_value = serializers.IntegerField(
        min_value=1,
        allow_null=True,
        required=False,
        help_text="Maximum number of exception events ingested per bucket for the entire project. Null removes the limit.",
    )
    project_rate_limit_bucket_size_minutes = serializers.IntegerField(
        min_value=1,
        allow_null=True,
        required=False,
        help_text="Bucket window over which the project-wide rate limit applies, in minutes.",
    )

    class Meta:
        model = ErrorTrackingSettings
        fields = ["project_rate_limit_value", "project_rate_limit_bucket_size_minutes"]


@extend_schema(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingSettingsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "error_tracking"

    def _get_or_create_settings(self) -> ErrorTrackingSettings:
        settings, _ = ErrorTrackingSettings.objects.get_or_create(team=self.team)
        return settings

    @extend_schema(responses={200: ErrorTrackingSettingsSerializer})
    @action(detail=False, methods=["get"])
    def retrieve_settings(self, request, *args, **kwargs):
        settings = self._get_or_create_settings()
        serializer = ErrorTrackingSettingsSerializer(settings)
        return Response(serializer.data)

    @extend_schema(
        request=ErrorTrackingSettingsSerializer,
        responses={200: ErrorTrackingSettingsSerializer},
    )
    @action(detail=False, methods=["patch"])
    def update_settings(self, request, *args, **kwargs):
        settings = self._get_or_create_settings()
        serializer = ErrorTrackingSettingsSerializer(settings, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
