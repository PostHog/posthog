import re
from typing import Any

from django.db import transaction

from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer

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
        normalized = value.replace("\\", "/")
        parts = normalized.split("/")
        if any(part == ".." for part in parts):
            raise serializers.ValidationError("File paths must not contain '..' traversal segments.")
        if normalized.startswith("/"):
            raise serializers.ValidationError("File paths must be relative, not absolute.")
        return value

    def validate_content(self, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_SKILL_FILE_BYTES:
            raise serializers.ValidationError(
                f"File content must be {MAX_SKILL_FILE_BYTES} bytes or fewer.",
                code="max_size",
            )
        return value


class LLMSkillPublishSerializer(serializers.Serializer):
    body = serializers.CharField(
        required=False,
        help_text="Full skill body (SKILL.md instruction content) to publish as a new version.",
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
        help_text="Bundled files to include with this version. Replaces all files from the previous version.",
    )
    base_version = serializers.IntegerField(
        min_value=1,
        help_text="Latest version you are editing from. Used for optimistic concurrency checks.",
    )

    def validate_body(self, value: str) -> str:
        return validate_skill_body_size(value)

    def validate_files(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _validate_files(value)


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
    files = LLMSkillFileInputSerializer(
        many=True,
        required=False,
        write_only=True,
        help_text="Bundled files to include with the initial version (scripts, references, assets).",
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

    def validate_name(self, value: str) -> str:
        return validate_skill_name_value(value)

    def validate_body(self, value: str) -> str:
        return validate_skill_body_size(value)

    def validate_files(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _validate_files(value)

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
    """List serializer that omits the body field for progressive disclosure (Level 1)."""

    class Meta(LLMSkillSerializer.Meta):
        fields = [f for f in LLMSkillSerializer.Meta.fields if f != "body"]
        read_only_fields = [f for f in LLMSkillSerializer.Meta.read_only_fields if f != "body"]


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
