from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.facade import api as error_tracking_api


class ErrorTrackingSettingsSerializer(serializers.Serializer):
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
    per_issue_rate_limit_value = serializers.IntegerField(
        min_value=1,
        allow_null=True,
        required=False,
        help_text="Maximum number of exception events ingested per bucket for each individual issue. Null removes the limit.",
    )
    per_issue_rate_limit_bucket_size_minutes = serializers.IntegerField(
        min_value=1,
        allow_null=True,
        required=False,
        help_text="Bucket window over which the per-issue rate limit applies, in minutes.",
    )


class ErrorTrackingSettingsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "error_tracking"
    scope_object_read_actions = ["retrieve_settings"]
    scope_object_write_actions = ["update_settings"]

    @extend_schema(responses={200: ErrorTrackingSettingsSerializer})
    @action(detail=False, methods=["get"])
    def retrieve_settings(self, request, *args, **kwargs):
        settings = error_tracking_api.get_settings(self.team.id)
        return Response(ErrorTrackingSettingsSerializer(settings).data)

    @extend_schema(
        request=ErrorTrackingSettingsSerializer,
        responses={200: ErrorTrackingSettingsSerializer},
    )
    @action(detail=False, methods=["patch"])
    def update_settings(self, request, *args, **kwargs):
        serializer = ErrorTrackingSettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        settings = error_tracking_api.update_settings(self.team.id, dict(serializer.validated_data))
        return Response(ErrorTrackingSettingsSerializer(settings).data, status=status.HTTP_200_OK)
