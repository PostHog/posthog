from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.facade import api as error_tracking_api
from products.error_tracking.backend.facade.contracts import AUTO_RESOLVE_MAX_DAYS, AUTO_RESOLVE_MIN_DAYS


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
    auto_resolve_after_days = serializers.IntegerField(
        min_value=AUTO_RESOLVE_MIN_DAYS,
        max_value=AUTO_RESOLVE_MAX_DAYS,
        allow_null=True,
        required=False,
        help_text=(
            "Resolve active issues automatically once they have had no exceptions for this many days, from 1 to 365. "
            "A daily run resolves them. Null turns auto-resolve off."
        ),
    )


class AutoResolvePreviewQuerySerializer(serializers.Serializer):
    days = serializers.IntegerField(
        min_value=AUTO_RESOLVE_MIN_DAYS,
        max_value=AUTO_RESOLVE_MAX_DAYS,
        help_text="Number of days without exceptions after which an active issue counts as quiet, from 1 to 365.",
    )


class AutoResolvePreviewSerializer(serializers.Serializer):
    count = serializers.IntegerField(
        help_text="Number of active issues the next auto-resolve run would resolve with this number of days."
    )


class ErrorTrackingSettingsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "error_tracking"
    scope_object_read_actions = ["retrieve_settings", "auto_resolve_preview"]
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

    @extend_schema(
        parameters=[AutoResolvePreviewQuerySerializer],
        responses={200: AutoResolvePreviewSerializer},
    )
    @action(detail=False, methods=["get"])
    def auto_resolve_preview(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query = AutoResolvePreviewQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        count = error_tracking_api.count_auto_resolve_candidates(self.team.id, query.validated_data["days"])
        return Response(AutoResolvePreviewSerializer({"count": count}).data)
