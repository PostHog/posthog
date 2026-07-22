from typing import TYPE_CHECKING, cast

import posthoganalytics
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView
from rest_framework_dataclasses.serializers import DataclassSerializer

from products.streamlit_apps.backend.facade.contracts import (
    AppContract,
    AppSandboxContract,
    AppVersionContract,
    CreateAppInput,
    StreamlitAppUserInfo,
    UpdateAppInput,
)

if TYPE_CHECKING:
    from posthog.api.routing import TeamAndOrgViewSetMixin
    from posthog.models.user import User

# --- Output Serializers ---


class StreamlitAppUserSerializer(DataclassSerializer):
    class Meta:
        dataclass = StreamlitAppUserInfo


class StreamlitAppVersionSerializer(DataclassSerializer):
    created_by = StreamlitAppUserSerializer(
        allow_null=True, required=False, help_text="User who uploaded this version."
    )

    class Meta:
        dataclass = AppVersionContract


class StreamlitAppSandboxSerializer(DataclassSerializer):
    class Meta:
        dataclass = AppSandboxContract


class StreamlitAppMinimalSerializer(DataclassSerializer):
    created_by = StreamlitAppUserSerializer(allow_null=True, required=False, help_text="User who created this app.")

    class Meta:
        dataclass = AppContract
        exclude = ["active_version", "sandbox"]


class StreamlitAppSerializer(DataclassSerializer):
    created_by = StreamlitAppUserSerializer(allow_null=True, required=False, help_text="User who created this app.")
    active_version = StreamlitAppVersionSerializer(
        allow_null=True, required=False, help_text="Currently active version, or null if none uploaded yet."
    )
    sandbox = StreamlitAppSandboxSerializer(
        allow_null=True, required=False, help_text="Current sandbox state, or null if the app has never started."
    )

    class Meta:
        dataclass = AppContract


# --- Input Serializers ---


class CreateAppInputSerializer(DataclassSerializer):
    name = serializers.CharField(help_text="Name of the app.")
    description = serializers.CharField(required=False, allow_blank=True, help_text="Optional description of the app.")
    cpu_cores = serializers.FloatField(required=False, help_text="CPU cores allocated to the sandbox.")
    memory_gb = serializers.FloatField(required=False, help_text="Memory in GB allocated to the sandbox.")

    class Meta:
        dataclass = CreateAppInput


class UpdateAppInputSerializer(DataclassSerializer):
    name = serializers.CharField(required=False, help_text="New name for the app.")
    description = serializers.CharField(required=False, allow_blank=True, help_text="New description for the app.")
    cpu_cores = serializers.FloatField(required=False, help_text="New CPU core allocation for the sandbox.")
    memory_gb = serializers.FloatField(required=False, help_text="New memory (GB) allocation for the sandbox.")

    class Meta:
        dataclass = UpdateAppInput


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
        distinct_id = cast("User", user).distinct_id or str(organization.id)
        return streamlit_apps_flag_enabled(distinct_id, str(organization.id))
