import re
from typing import Any

from django.db import transaction

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer

from ..markdown_outline import get_markdown_outline
from ..models.skills import LLMSkill, LLMSkillFile

RESERVED_SKILL_NAMES = {"new"}
DEFAULT_VERSION_PAGE_SIZE = 50
MAX_SKILL_BODY_BYTES = 1_000_000
MAX_SKILL_FILE_BYTES = 1_000_000
MAX_SKILL_FILE_COUNT = 50
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def validate_skill_name_value(value: str) -> str:
    if value.lower() in RESERVED_SKILL_NAMES:
        raise serializers.ValidationError(
            "'new' is a reserved name and cannot be used.",
            code="reserved_name",
        )
    if len(value) > 64:
        raise serializers.ValidationError(
            "Skill name must be 64 characters or fewer.",
            code="max_length",
        )
    if not SKILL_NAME_PATTERN.match(value):
        raise serializers.ValidationError(
            "Only lowercase letters, numbers, and hyphens are allowed. "
            "Must not start or end with a hyphen or contain consecutive hyphens.",
            code="invalid_name",
        )
    if "--" in value:
        raise serializers.ValidationError(
            "Consecutive hyphens are not allowed.",
            code="invalid_name",
        )
    return value


def validate_skill_file_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if any(part == ".." for part in parts):
        raise serializers.ValidationError("File paths must not contain '..' traversal segments.")
    if normalized.startswith("/"):
        raise serializers.ValidationError("File paths must be relative, not absolute.")
    return value


def _validate_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(files) > MAX_SKILL_FILE_COUNT:
        raise serializers.ValidationError(
            f"A skill may contain at most {MAX_SKILL_FILE_COUNT} files.",
            code="max_count",
        )
    paths = [f["path"] for f in files]
    if len(paths) != len(set(paths)):
        raise serializers.ValidationError("Duplicate file paths are not allowed.")
    return files


def validate_skill_body_size(body: str) -> str:
    body_bytes = len(body.encode("utf-8"))
    if body_bytes > MAX_SKILL_BODY_BYTES:
        raise serializers.ValidationError(
            f"Skill body must be {MAX_SKILL_BODY_BYTES} bytes or fewer.",
            code="max_size",
        )
    return body


class LLMSkillFetchQuerySerializer(serializers.Serializer):
    version = serializers.IntegerField(
        min_value=1,
        required=False,
        help_text="Specific skill version to fetch. If omitted, the latest version is returned.",
    )


class LLMSkillListQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional substring filter applied to skill names and descriptions.",
    )


class LLMSkillResolveQuerySerializer(LLMSkillFetchQuerySerializer):
    version_id = serializers.UUIDField(
        required=False,
        help_text="Exact skill version UUID to resolve.",
    )
    offset = serializers.IntegerField(
        min_value=0,
        required=False,
        help_text="Zero-based offset into version history for pagination. Mutually exclusive with before_version.",
    )
    before_version = serializers.IntegerField(
        min_value=1,
        required=False,
        help_text="Return versions older than this version number. Mutually exclusive with offset.",
    )
    limit = serializers.IntegerField(
        min_value=1,
        required=False,
        default=DEFAULT_VERSION_PAGE_SIZE,
        max_value=100,
        help_text="Maximum number of versions to return per page (1-100).",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("offset") is not None and attrs.get("before_version") is not None:
            raise serializers.ValidationError("Use either offset or before_version, not both.")
        return attrs


class LLMSkillOutlineEntrySerializer(serializers.Serializer):
    level = serializers.IntegerField(min_value=1, max_value=6, help_text="Markdown heading level (1-6).")
    text = serializers.CharField(help_text="Heading text.")


class LLMSkillFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = LLMSkillFile
        fields = ["path", "content", "content_type"]


class LLMSkillFileManifestSerializer(serializers.ModelSerializer):
    class Meta:
        model = LLMSkillFile
        fields = ["path", "content_type"]


class LLMSkillFileInputSerializer(serializers.Serializer):
    path = serializers.CharField(
        max_length=500,
        help_text="File path relative to skill root, e.g. 'scripts/setup.sh' or 'references/guide.md'.",
    )
    content = serializers.CharField(
        help_text="Text content of the file.",
    )
    content_type = serializers.CharField(
        max_length=100,
        required=False,
        default="text/plain",
        help_text="MIME type of the file content.",
    )

    def validate_path(self, value: str) -> str:
        return validate_skill_file_path(value)

    def validate_content(self, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_SKILL_FILE_BYTES:
            raise serializers.ValidationError(
                f"File content must be {MAX_SKILL_FILE_BYTES} bytes or fewer.",
                code="max_size",
            )
        return value


class LLMSkillEditOperationSerializer(serializers.Serializer):
    # Reused for both top-level body edits and per-file edits (LLMSkillFileEditSerializer.edits),
    # so help_text must stay generic — the parent field's description provides the body/file context.
    old = serializers.CharField(
        help_text="Text to find in the target content. Must match exactly once.",
    )
    new = serializers.CharField(
        allow_blank=True,
        help_text="Replacement text.",
    )


class LLMSkillFileEditSerializer(serializers.Serializer):
    path = serializers.CharField(
        max_length=500,
        help_text="Path of the bundled file to edit. Must match an existing file on the current skill version.",
    )
    edits = LLMSkillEditOperationSerializer(
        many=True,
        help_text="Sequential find/replace operations to apply to this file's content.",
    )

    def validate_path(self, value: str) -> str:
        return validate_skill_file_path(value)

    def validate_edits(self, value: list[dict[str, str]]) -> list[dict[str, str]]:
        if len(value) == 0:
            raise serializers.ValidationError("At least one edit operation is required.")
        return value


class LLMSkillPublishSerializer(serializers.Serializer):
    body = serializers.CharField(
        required=False,
        help_text="Full skill body (SKILL.md instruction content) to publish as a new version. Mutually exclusive with edits.",
    )
    edits = LLMSkillEditOperationSerializer(
        many=True,
        required=False,
        help_text=(
            "List of find/replace operations to apply to the current skill body. "
            "Each edit's 'old' text must match exactly once. Edits are applied sequentially. "
            "Mutually exclusive with body."
        ),
    )
    description = serializers.CharField(
        max_length=4096,
        required=False,
        help_text="Updated description for the new version.",
    )
    license = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="License name or reference.",
    )
    compatibility = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        help_text="Environment requirements.",
    )
    allowed_tools = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="List of pre-approved tools the skill may use.",
    )
    metadata = serializers.DictField(
        required=False,
        help_text="Arbitrary key-value metadata.",
    )
    files = LLMSkillFileInputSerializer(
        many=True,
        required=False,
        help_text=(
            "Bundled files to include with this version. Replaces all files from the previous "
            "version. Mutually exclusive with file_edits."
        ),
    )
    file_edits = LLMSkillFileEditSerializer(
        many=True,
        required=False,
        help_text=(
            "Per-file find/replace updates. Each entry targets one existing file by path and "
            "applies sequential edits to its content. Non-targeted files carry forward unchanged. "
            "Cannot add, remove, or rename files — use 'files' for that. Mutually exclusive with files."
        ),
    )
    base_version = serializers.IntegerField(
        min_value=1,
        help_text="Latest version you are editing from. Used for optimistic concurrency checks.",
    )

    def validate_body(self, value: str) -> str:
        return validate_skill_body_size(value)

    def validate_edits(self, value: list[dict[str, str]]) -> list[dict[str, str]]:
        if len(value) == 0:
            raise serializers.ValidationError("At least one edit operation is required.")
        return value

    def validate_files(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _validate_files(value)

    def validate_file_edits(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(value) == 0:
            raise serializers.ValidationError("At least one file_edits entry is required.")
        paths = [entry["path"] for entry in value]
        if len(paths) != len(set(paths)):
            raise serializers.ValidationError("Duplicate file paths are not allowed in file_edits.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "body" in attrs and "edits" in attrs:
            raise serializers.ValidationError("Provide either 'body' or 'edits', not both.")
        if "files" in attrs and "file_edits" in attrs:
            raise serializers.ValidationError("Provide either 'files' or 'file_edits', not both.")
        return attrs


class LLMSkillSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    is_latest = serializers.SerializerMethodField()
    latest_version = serializers.SerializerMethodField()
    version_count = serializers.SerializerMethodField()
    first_version_created_at = serializers.SerializerMethodField()
    allowed_tools = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="List of pre-approved tools the skill may use.",
    )
    metadata = serializers.DictField(
        required=False,
        default=dict,
        help_text="Arbitrary key-value metadata.",
    )
    files = serializers.SerializerMethodField(
        help_text="Bundled files manifest. Each entry is path + content_type only; fetch content via /llm_skills/name/{name}/files/{path}/.",
    )
    outline = serializers.SerializerMethodField(
        help_text="Flat list of markdown headings parsed from the skill body. Useful as a lightweight table of contents.",
    )

    class Meta:
        model = LLMSkill
        fields = [
            "id",
            "name",
            "description",
            "body",
            "license",
            "compatibility",
            "allowed_tools",
            "metadata",
            "files",
            "outline",
            "version",
            "created_by",
            "created_at",
            "updated_at",
            "deleted",
            "is_latest",
            "latest_version",
            "version_count",
            "first_version_created_at",
        ]
        read_only_fields = [
            "id",
            "files",
            "outline",
            "version",
            "created_by",
            "created_at",
            "updated_at",
            "deleted",
            "is_latest",
            "latest_version",
            "version_count",
            "first_version_created_at",
        ]
        extra_kwargs = {
            "name": {
                "help_text": "Unique skill name. Lowercase letters, numbers, and hyphens only. Max 64 characters."
            },
            "description": {"help_text": "What this skill does and when to use it. Max 4096 characters."},
            "body": {"help_text": "The SKILL.md instruction content (markdown)."},
            "license": {"help_text": "License name or reference to a bundled license file."},
            "compatibility": {
                "help_text": "Environment requirements (intended product, system packages, network access, etc.)."
            },
            "metadata": {"help_text": "Arbitrary key-value metadata."},
        }

    def get_is_latest(self, instance: LLMSkill) -> bool:
        return bool(getattr(instance, "is_latest", False))

    def get_latest_version(self, instance: LLMSkill) -> int:
        return int(getattr(instance, "latest_version", instance.version))

    def get_version_count(self, instance: LLMSkill) -> int:
        return int(getattr(instance, "version_count", 1))

    def get_first_version_created_at(self, instance: LLMSkill) -> str:
        value = getattr(instance, "first_version_created_at", instance.created_at)
        if value is None:
            value = instance.created_at
        if isinstance(value, str):
            return value
        return value.isoformat().replace("+00:00", "Z")

    @extend_schema_field(LLMSkillFileManifestSerializer(many=True))
    def get_files(self, instance: LLMSkill) -> list[dict[str, Any]]:
        return [dict(row) for row in LLMSkillFile.objects.filter(skill=instance).values("path", "content_type")]

    @extend_schema_field(LLMSkillOutlineEntrySerializer(many=True))
    def get_outline(self, instance: LLMSkill) -> list[dict[str, Any]]:
        return get_markdown_outline(instance.body)

    def validate_name(self, value: str) -> str:
        return validate_skill_name_value(value)

    def validate_body(self, value: str) -> str:
        return validate_skill_body_size(value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        team = self.context["get_team"]()
        name = attrs.get("name")

        if self.instance is None:
            if name and LLMSkill.objects.filter(name=name, team=team, deleted=False).exists():
                raise serializers.ValidationError({"name": "A skill with this name already exists."}, code="unique")
            return attrs

        if name is not None and self.instance.name != name:
            raise serializers.ValidationError(
                {"name": "Skill name cannot be changed after creation."},
                code="immutable",
            )

        return attrs


class LLMSkillCreateSerializer(LLMSkillSerializer):
    """Create serializer — accepts bundled files as write-only input on POST."""

    files = LLMSkillFileInputSerializer(  # type: ignore[assignment]
        many=True,
        required=False,
        write_only=True,
        help_text="Bundled files to include with the initial version (scripts, references, assets).",
    )

    class Meta(LLMSkillSerializer.Meta):
        read_only_fields = [f for f in LLMSkillSerializer.Meta.read_only_fields if f != "files"]

    def validate_files(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _validate_files(value)

    def create(self, validated_data: dict[str, Any]) -> LLMSkill:
        request = self.context["request"]
        team = self.context["get_team"]()
        files = validated_data.pop("files", None)

        with transaction.atomic():
            skill = LLMSkill.objects.create(
                team=team,
                created_by=request.user,
                is_latest=True,
                **validated_data,
            )
            if files:
                LLMSkillFile.objects.bulk_create(
                    [
                        LLMSkillFile(
                            skill=skill,
                            path=f["path"],
                            content=f["content"],
                            content_type=f.get("content_type", "text/plain"),
                        )
                        for f in files
                    ]
                )
        return skill


class LLMSkillListSerializer(LLMSkillSerializer):
    """List serializer that omits body and file manifest — progressive disclosure (Level 1)."""

    class Meta(LLMSkillSerializer.Meta):
        fields = [f for f in LLMSkillSerializer.Meta.fields if f not in ("body", "files")]
        read_only_fields = [f for f in LLMSkillSerializer.Meta.read_only_fields if f not in ("body", "files")]


class LLMSkillVersionSummarySerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = LLMSkill
        fields = [
            "id",
            "version",
            "created_by",
            "created_at",
            "is_latest",
        ]
        read_only_fields = fields


class LLMSkillDuplicateSerializer(serializers.Serializer):
    new_name = serializers.CharField(
        max_length=64,
        help_text="Name for the duplicated skill. Must be unique.",
    )

    def validate_new_name(self, value: str) -> str:
        return validate_skill_name_value(value)


class LLMSkillResolveResponseSerializer(serializers.Serializer):
    skill = LLMSkillSerializer()
    versions = LLMSkillVersionSummarySerializer(many=True)
    has_more = serializers.BooleanField()


class LLMSkillFileCreateSerializer(LLMSkillFileInputSerializer):
    base_version = serializers.IntegerField(
        min_value=1,
        required=False,
        help_text=(
            "Latest version you are editing from. If provided, the request fails with 409 "
            "when another write has landed in the meantime."
        ),
    )


class LLMSkillFileRenameSerializer(serializers.Serializer):
    old_path = serializers.CharField(
        max_length=500,
        help_text="Current file path to rename.",
    )
    new_path = serializers.CharField(
        max_length=500,
        help_text="New file path. Must not already exist in the skill.",
    )
    base_version = serializers.IntegerField(
        min_value=1,
        required=False,
        help_text=(
            "Latest version you are editing from. If provided, the request fails with 409 "
            "when another write has landed in the meantime."
        ),
    )

    def validate_old_path(self, value: str) -> str:
        return validate_skill_file_path(value)

    def validate_new_path(self, value: str) -> str:
        return validate_skill_file_path(value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["old_path"] == attrs["new_path"]:
            raise serializers.ValidationError("new_path must differ from old_path.")
        return attrs


class LLMSkillFileDeleteQuerySerializer(serializers.Serializer):
    base_version = serializers.IntegerField(
        min_value=1,
        required=False,
        help_text=(
            "Latest version you are editing from. If provided, the request fails with 409 "
            "when another write has landed in the meantime."
        ),
    )
