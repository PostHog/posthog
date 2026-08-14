from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.facade import (
    api as error_tracking_api,
    setup as error_tracking_setup,
)


class ErrorTrackingObservedSDKSerializer(serializers.Serializer):
    library = serializers.CharField(help_text="SDK library observed on recent project events.")
    event_count = serializers.IntegerField(
        min_value=0,
        help_text="Number of recent events observed from this SDK library.",
    )
    autocapture_configuration = serializers.ChoiceField(
        choices=["project_setting", "local", "unknown"],
        help_text="Where exception autocapture is configured for this SDK.",
    )
    local_option = serializers.CharField(
        allow_null=True,
        help_text="SDK initialization option required for local exception autocapture, when known.",
    )


class ErrorTrackingSetupWarningSerializer(serializers.Serializer):
    warning_code = serializers.ChoiceField(
        source="code",
        choices=["node_autocapture_requires_local_configuration"],
        help_text="Stable identifier for the setup warning.",
    )
    message = serializers.CharField(help_text="Actionable explanation of the setup warning.")


class ErrorTrackingSetupStatusSerializer(serializers.Serializer):
    project_autocapture_enabled = serializers.BooleanField(
        help_text="Whether exception autocapture is enabled in the current project settings.",
    )
    remote_config_autocapture_enabled = serializers.BooleanField(
        allow_null=True,
        help_text="Published exception autocapture value, or null when remote config is unavailable.",
    )
    has_issues = serializers.BooleanField(help_text="Whether the project has any grouped error tracking issues.")
    recent_data_available = serializers.BooleanField(
        help_text="Whether recent event ingestion data was available for this diagnostic.",
    )
    recent_period_days = serializers.IntegerField(
        min_value=1,
        help_text="Number of days covered by recent event and SDK observations.",
    )
    recent_event_count = serializers.IntegerField(
        min_value=0,
        allow_null=True,
        help_text="Total events received during the recent period, or null when recent data is unavailable.",
    )
    recent_exception_count = serializers.IntegerField(
        min_value=0,
        allow_null=True,
        help_text="Exception events received during the recent period, or null when recent data is unavailable.",
    )
    observed_sdks = ErrorTrackingObservedSDKSerializer(
        many=True,
        help_text="SDK libraries observed on events during the recent period.",
    )
    warnings = ErrorTrackingSetupWarningSerializer(
        many=True,
        help_text="Setup warnings supported by observed project data.",
    )


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
    scope_object_read_actions = ["retrieve_settings", "setup_status"]
    scope_object_write_actions = ["update_settings"]

    @extend_schema(responses={200: ErrorTrackingSetupStatusSerializer})
    @action(detail=False, methods=["get"], url_path="setup_status")
    def setup_status(self, request: Request, *args: object, **kwargs: object) -> Response:
        setup_status = error_tracking_setup.get_error_tracking_setup_status(self.team)
        return Response(ErrorTrackingSetupStatusSerializer(setup_status).data)

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
