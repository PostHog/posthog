import base64
import binascii
from collections import Counter
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
    AppSourceFileContract,
    AppVersionContract,
    AppVersionSourceContract,
    CreateAppInput,
    CreateVersionFromSourceInput,
    EditVersionSourceInput,
    SourceFileEdit,
    SourceTextEdit,
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
# Each edit scans and copies the whole text of its file, so the edit count bounds the work of one request.
_MAX_SOURCE_EDITS = 100
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


class StreamlitAppSourceFileSerializer(DataclassSerializer):
    path = serializers.CharField(
        help_text="Project-relative path of the file, for example 'app.py' or 'pages/1_Overview.py'."
    )
    size = serializers.IntegerField(help_text="File size in bytes.")
    sha256 = serializers.CharField(help_text="SHA-256 hash of the file bytes, as hex.")
    content_type = serializers.CharField(help_text="MIME type guessed from the file extension.")
    is_binary = serializers.BooleanField(
        help_text="True when the file is not UTF-8 text. Binary content is never inlined."
    )
    content = serializers.CharField(
        allow_null=True,
        trim_whitespace=False,
        help_text="Full text of the file. Null for binary files and for files that the paths filter excludes.",
    )

    class Meta:
        dataclass = AppSourceFileContract


class StreamlitAppVersionSourceSerializer(DataclassSerializer):
    version_number = serializers.IntegerField(help_text="Version number that this source belongs to.")
    files = StreamlitAppSourceFileSerializer(
        many=True, help_text="Every file in the version, sorted by path. The manifest always lists all files."
    )

    class Meta:
        dataclass = AppVersionSourceContract


class VersionSourceQuerySerializer(serializers.Serializer):
    version_number = serializers.IntegerField(
        required=False, min_value=1, help_text="Version number to read. Defaults to the active version."
    )
    paths = serializers.CharField(
        required=False,
        help_text=(
            "Comma-separated file paths whose content to return, for example 'app.py,utils.py'. "
            "Other files appear in the manifest without content. Defaults to all text files."
        ),
    )

    def validate_paths(self, value: str) -> list[str]:
        return [path.strip() for path in value.split(",") if path.strip()]


class SourceTextEditSerializer(DataclassSerializer):
    old = serializers.CharField(
        trim_whitespace=False,
        allow_blank=True,
        help_text="Exact text to find in the file. Must match exactly once. Use an empty string only to fill an empty file.",
    )
    new = serializers.CharField(trim_whitespace=False, allow_blank=True, help_text="Replacement text.")

    class Meta:
        dataclass = SourceTextEdit


class SourceFileEditSerializer(DataclassSerializer):
    path = serializers.CharField(help_text="Path of an existing text file in the base version, for example 'app.py'.")
    edits = SourceTextEditSerializer(
        many=True,
        help_text=(
            "Find-and-replace operations, applied in order to the file's text. "
            f"At most {_MAX_SOURCE_EDITS} edits per request across all files."
        ),
    )

    def validate_edits(self, value: list[SourceTextEdit]) -> list[SourceTextEdit]:
        if not value:
            raise serializers.ValidationError("At least one edit is required.")
        return value

    class Meta:
        dataclass = SourceFileEdit


class EditVersionSourceInputSerializer(DataclassSerializer):
    base_version = serializers.IntegerField(
        min_value=1,
        help_text=(
            "Version number that the changes apply to. Must be the active version of the app, "
            "otherwise the request fails with 409 and returns the active version number."
        ),
    )
    file_edits = SourceFileEditSerializer(
        many=True,
        required=False,
        help_text="Exact text edits to existing text files. Files that no change touches stay byte-for-byte the same.",
    )
    create_files = serializers.DictField(
        child=serializers.CharField(trim_whitespace=False, allow_blank=True, max_length=_MAX_TEXT_FILE_LENGTH),
        required=False,
        help_text=(
            "New text files keyed by project-relative path, each value the file's full text (max 1 MB). "
            "The path must not exist in the base version."
        ),
    )
    delete_files = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Paths of files to remove from the base version. app.py cannot be removed.",
    )

    def validate_create_files(self, value: dict[str, str]) -> dict[str, str]:
        return _validate_attachment_paths(value)

    def validate(self, attrs: EditVersionSourceInput) -> EditVersionSourceInput:
        if not (attrs.file_edits or attrs.create_files or attrs.delete_files):
            raise serializers.ValidationError("Provide at least one of file_edits, create_files, or delete_files.")
        for name, collection in (
            ("file_edits", attrs.file_edits),
            ("create_files", attrs.create_files),
            ("delete_files", attrs.delete_files),
        ):
            if len(collection) > MAX_FILE_COUNT:
                raise serializers.ValidationError(
                    f"Too many files in {name} ({len(collection)}, max {MAX_FILE_COUNT})."
                )
        if sum(len(file_edit.edits) for file_edit in attrs.file_edits) > _MAX_SOURCE_EDITS:
            raise serializers.ValidationError(
                f"Send at most {_MAX_SOURCE_EDITS} edits per request. Split larger changes across several requests."
            )
        touched = [edit.path for edit in attrs.file_edits] + list(attrs.create_files) + list(attrs.delete_files)
        duplicates = sorted(path for path, count in Counter(touched).items() if count > 1)
        if duplicates:
            raise serializers.ValidationError(f"Each path can appear in only one change: {', '.join(duplicates)}")
        return attrs

    class Meta:
        dataclass = EditVersionSourceInput


class SourceEditErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the change could not be applied.")
    path = serializers.CharField(allow_null=True, help_text="Path of the file that caused the error, if any.")
    edit_index = serializers.IntegerField(
        allow_null=True, help_text="Zero-based index of the failed edit inside that file's edits, if any."
    )


class VersionConflictSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the change was refused.")
    current_version = serializers.IntegerField(help_text="Active version number of the app. Read it and retry.")


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
