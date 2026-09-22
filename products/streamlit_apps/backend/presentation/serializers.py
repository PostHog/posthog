import base64
import binascii
from typing import TYPE_CHECKING, cast

import posthoganalytics
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView
from rest_framework_dataclasses.serializers import DataclassSerializer

from products.streamlit_apps.backend.facade.api import MAX_FILE_COUNT, MAX_ZIP_SIZE, attachment_path_error
from products.streamlit_apps.backend.facade.contracts import (
    AppContract,
    AppSandboxContract,
    AppVersionContract,
    CreateAppInput,
    CreateVersionFromSourceInput,
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


# Shares AppContract with StreamlitAppSerializer, so without its own component name the two
# collapse into one schema and the fuller one loses active_version/sandbox.
@extend_schema_serializer(component_name="AppSummaryContract")
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


_MAX_TEXT_FILE_LENGTH = 1024 * 1024
# Base64 length of MAX_ZIP_SIZE bytes: no single asset can be larger than the whole archive may be.
_MAX_ASSET_BASE64_LENGTH = 4 * ((MAX_ZIP_SIZE + 2) // 3)


def _decoded_base64_size(encoded: str) -> int:
    return len(encoded) * 3 // 4 - (2 if encoded.endswith("==") else 1 if encoded.endswith("=") else 0)


class CreateVersionFromSourceInputSerializer(DataclassSerializer):
    # "source" is the natural API field name; it shadows DRF's Field.source attribute
    # only in the eyes of mypy — DRF handles same-named declared fields fine.
    source = serializers.CharField(  # type: ignore[assignment]
        trim_whitespace=False,
        # Bounds the JSON body before any zip is built; the multipart path gets the
        # same protection from the declared-size check against MAX_ZIP_SIZE.
        max_length=_MAX_TEXT_FILE_LENGTH,
        help_text=(
            "Full Python source for the Streamlit app's root app.py file, as free text (max 1 MB). "
            "Becomes a new version and is set as the active version."
        ),
    )

    files = serializers.DictField(
        child=serializers.CharField(trim_whitespace=False, allow_blank=True, max_length=_MAX_TEXT_FILE_LENGTH),
        required=False,
        help_text=(
            "Extra text files to ship next to app.py, keyed by project-relative path "
            "(for example 'utils.py' or 'data/config.json'), each as plain text (max 1 MB)."
        ),
    )
    assets = serializers.DictField(
        child=serializers.CharField(max_length=_MAX_ASSET_BASE64_LENGTH),
        required=False,
        help_text=(
            "Extra binary files to ship next to app.py, keyed by project-relative path "
            "(for example 'data/events.parquet'), each as standard base64 text."
        ),
    )

    def validate_source(self, value: str) -> str:
        # allow_blank already rejects "", but trim_whitespace=False (needed to preserve
        # indentation) would otherwise let whitespace-only source through and serve a
        # blank app with no error anywhere.
        if not value.strip():
            raise serializers.ValidationError("Source cannot be empty.")
        return value

    def validate_files(self, value: dict[str, str]) -> dict[str, str]:
        return _validate_attachment_paths(value)

    def validate_assets(self, value: dict[str, str]) -> dict[str, str]:
        _validate_attachment_paths(value)
        for path, content in value.items():
            try:
                base64.b64decode(content, validate=True)
            except (binascii.Error, ValueError):
                raise serializers.ValidationError({path: "Content must be standard base64 text."}) from None
        return value

    def validate(self, attrs: CreateVersionFromSourceInput) -> CreateVersionFromSourceInput:
        overlap = sorted(set(attrs.files) & set(attrs.assets))
        if overlap:
            raise serializers.ValidationError({"assets": f"Paths also present in files: {', '.join(overlap)}"})

        entry_count = 1 + len(attrs.files) + len(attrs.assets)
        if entry_count > MAX_FILE_COUNT:
            raise serializers.ValidationError(f"Too many files ({entry_count}, max {MAX_FILE_COUNT}).")

        # A path that is also a directory prefix of another cannot be unpacked on any filesystem.
        paths = {"app.py", *attrs.files, *attrs.assets}
        for path in sorted(paths):
            if any(other.startswith(f"{path}/") for other in paths):
                raise serializers.ValidationError(f"'{path}' is used as both a file and a directory.")

        # Bound the work before any asset is decoded or the archive is built. The zip check
        # after compression stays, this only refuses what could never fit.
        raw_size = (
            len(attrs.source.encode())
            + sum(len(text.encode()) for text in attrs.files.values())
            + sum(_decoded_base64_size(content) for content in attrs.assets.values())
        )
        if raw_size > MAX_ZIP_SIZE:
            raise serializers.ValidationError(
                f"App files total {raw_size / (1024 * 1024):.1f} MB, max {MAX_ZIP_SIZE / (1024 * 1024):.1f} MB."
            )
        return attrs

    class Meta:
        dataclass = CreateVersionFromSourceInput


def _validate_attachment_paths(value: dict[str, str]) -> dict[str, str]:
    errors = {path: error for path in value if (error := attachment_path_error(path))}
    if errors:
        raise serializers.ValidationError(errors)
    return value


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
