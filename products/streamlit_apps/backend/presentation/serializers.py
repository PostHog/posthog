from typing import Any

import posthoganalytics
from loginas.utils import is_impersonated_session
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.api.shared import UserBasicSerializer
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity

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
        fields = [
            "id",
            "version_number",
            "zip_file",
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

    def get_restart_count(self, obj: StreamlitAppSandbox) -> int:
        return obj.app.restart_count

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
        return streamlit_apps_flag_enabled(user.distinct_id, str(view.organization.id))
