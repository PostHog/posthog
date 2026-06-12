from typing import TYPE_CHECKING, Any, cast

import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from loginas.utils import is_impersonated_session
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.api.shared import UserBasicSerializer
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.user import User

if TYPE_CHECKING:
    from posthog.api.routing import TeamAndOrgViewSetMixin

from products.streamlit_apps.backend.models import (
    MAX_CPU_CORES,
    MAX_MEMORY_GB,
    MIN_CPU_CORES,
    MIN_MEMORY_GB,
    StreamlitApp,
    StreamlitAppSandbox,
    StreamlitAppVersion,
)


class StreamlitAppVersionSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = StreamlitAppVersion
        # `zip_file` (the object-storage key) is deliberately omitted — the client
        # never needs the raw storage path, and exposing it leaks the internal
        # tenant→path layout. Add a signed-URL endpoint instead if downloads are needed.
        fields = [
            "id",
            "version_number",
            "zip_hash",
            "snapshot_id",
            "created_by",
            "created_at",
        ]
        read_only_fields = fields


class StreamlitAppSandboxSerializer(serializers.ModelSerializer):
    restart_count = serializers.SerializerMethodField()
    version_number = serializers.SerializerMethodField()

    class Meta:
        model = StreamlitAppSandbox
        fields = [
            "status",
            "restart_count",
            "last_error",
            "started_at",
            "last_activity_at",
            "version_number",
        ]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.INT)
    def get_restart_count(self, obj: StreamlitAppSandbox) -> int:
        return obj.app.restart_count

    @extend_schema_field(OpenApiTypes.INT)
    def get_version_number(self, obj: StreamlitAppSandbox) -> int | None:
        return obj.version.version_number if obj.version else None


class StreamlitAppMinimalSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    status = serializers.SerializerMethodField()

    class Meta:
        model = StreamlitApp
        fields = [
            "id",
            "short_id",
            "name",
            "description",
            "cpu_cores",
            "memory_gb",
            "status",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.STR)
    def get_status(self, obj: StreamlitApp) -> str:
        try:
            return obj.sandbox.status
        except StreamlitAppSandbox.DoesNotExist:
            return "stopped"


class StreamlitAppSerializer(StreamlitAppMinimalSerializer):
    active_version = StreamlitAppVersionSerializer(read_only=True)
    sandbox = StreamlitAppSandboxSerializer(read_only=True)

    class Meta:
        model = StreamlitApp
        fields = [
            "id",
            "short_id",
            "name",
            "description",
            "cpu_cores",
            "memory_gb",
            "active_version",
            "sandbox",
            "status",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "short_id",
            "active_version",
            "sandbox",
            "status",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate_cpu_cores(self, value: float) -> float:
        if value < MIN_CPU_CORES or value > MAX_CPU_CORES:
            raise serializers.ValidationError(f"CPU cores must be between {MIN_CPU_CORES} and {MAX_CPU_CORES}.")
        return value

    def validate_memory_gb(self, value: float) -> float:
        if value < MIN_MEMORY_GB or value > MAX_MEMORY_GB:
            raise serializers.ValidationError(f"Memory must be between {MIN_MEMORY_GB} and {MAX_MEMORY_GB} GB.")
        return value

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> StreamlitApp:
        request = self.context["request"]
        team = self.context["get_team"]()

        app = StreamlitApp.objects.create(
            team=team,
            created_by=request.user,
            **validated_data,
        )

        log_activity(
            organization_id=request.user.current_organization_id,
            team_id=team.id,
            user=request.user,
            was_impersonated=is_impersonated_session(request),
            item_id=str(app.id),
            scope="StreamlitApp",
            activity="created",
            detail=Detail(name=app.name),
        )

        return app

    def update(self, instance: StreamlitApp, validated_data: dict, **kwargs: Any) -> StreamlitApp:
        before_update = StreamlitApp.objects.get(pk=instance.pk)
        updated_app = super().update(instance, validated_data)

        changes = changes_between("StreamlitApp", previous=before_update, current=updated_app)
        if changes:
            request = self.context["request"]
            log_activity(
                organization_id=request.user.current_organization_id,
                team_id=self.context["team_id"],
                user=request.user,
                was_impersonated=is_impersonated_session(request),
                item_id=str(instance.id),
                scope="StreamlitApp",
                activity="updated",
                detail=Detail(changes=changes, name=updated_app.name),
            )

        return updated_app


class StreamlitAppStatusSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="Sandbox lifecycle status, or 'stopped' when no sandbox exists.")
    restart_count = serializers.IntegerField(help_text="Number of times the app's sandbox has been restarted.")
    last_error = serializers.CharField(
        allow_blank=True, help_text="Most recent sandbox error message, empty when there is none."
    )
    started_at = serializers.DateTimeField(
        allow_null=True, help_text="When the current sandbox started, null when stopped."
    )
    last_activity_at = serializers.DateTimeField(
        allow_null=True, help_text="Timestamp of the last recorded viewer activity, null when none."
    )
    version_number = serializers.IntegerField(
        allow_null=True, required=False, help_text="Version number the running sandbox was booted from."
    )


class StreamlitAppVersionListSerializer(serializers.Serializer):
    results = StreamlitAppVersionSerializer(
        many=True, help_text="Most recent versions of the app, newest first (capped at 50)."
    )


class ActivateVersionRequestSerializer(serializers.Serializer):
    version_number = serializers.IntegerField(
        help_text="Version number to activate. Must reference an existing version of this app."
    )


class ActivateVersionResponseSerializer(serializers.Serializer):
    active_version = StreamlitAppVersionSerializer(help_text="The version that is now active for the app.")


class UploadVersionRequestSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="Zip archive containing the Streamlit app sources (max 10 MB).")


class StreamlitConnectInfoSerializer(serializers.Serializer):
    iframe_url = serializers.CharField(help_text="Authenticated URL to embed the running app in an iframe.")
    expires_in = serializers.IntegerField(help_text="Seconds until the embedded session credential expires.")


def streamlit_apps_flag_enabled(distinct_id: str, organization_id: str) -> bool:
    return bool(
        posthoganalytics.feature_enabled(
            "streamlit-apps",
            distinct_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )


class StreamlitAppsAccessPermission(BasePermission):
    message = "Streamlit apps is not available."

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        organization = cast("TeamAndOrgViewSetMixin", view).organization
        distinct_id = cast(User, user).distinct_id or str(organization.id)
        return streamlit_apps_flag_enabled(distinct_id, str(organization.id))
