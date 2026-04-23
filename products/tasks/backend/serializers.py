import base64
import binascii
from zoneinfo import available_timezones

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from croniter import croniter
from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field
from rest_framework import serializers

from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.api.shared import UserBasicSerializer
from posthog.models.integration import Integration
from posthog.storage import object_storage

from products.signals.backend.models import SignalReportTask

from .constants import (
    ALL_INITIAL_PERMISSION_MODE_CHOICES,
    CODEX_INITIAL_PERMISSION_MODE_CHOICES,
    INITIAL_PERMISSION_MODE_CHOICES,
)
from .models import SandboxEnvironment, Task, TaskAutomation, TaskRun
from .services.title_generator import generate_task_title
from .temporal.process_task.utils import (
    PUBLIC_REASONING_EFFORTS,
    LLMProvider,
    PrAuthorshipMode,
    RunSource,
    RunState,
    RuntimeAdapter,
    get_reasoning_effort_error,
    parse_run_state,
)

PRESIGNED_URL_CACHE_TTL = 55 * 60  # 55 minutes (less than 1 hour URL expiry)
TASK_RUN_ARTIFACT_MAX_SIZE_BYTES = 30 * 1024 * 1024
TASK_RUN_PDF_ARTIFACT_MAX_SIZE_BYTES = 10 * 1024 * 1024
TASK_RUN_ARTIFACT_TYPE_CHOICES = [
    "plan",
    "context",
    "reference",
    "output",
    "artifact",
    "tree_snapshot",
    "user_attachment",
]
TASK_RUN_ARTIFACT_CONTENT_ENCODING_CHOICES = ["utf-8", "base64"]


def get_task_run_artifact_max_size_bytes(
    artifact_name: str | None,
    content_type: str | None,
    artifact_type: str | None = None,
) -> int:
    if artifact_type != "user_attachment":
        return TASK_RUN_ARTIFACT_MAX_SIZE_BYTES

    normalized_name = (artifact_name or "").lower()
    normalized_content_type = (content_type or "").split(";")[0].strip().lower()

    if normalized_name.endswith(".pdf") or normalized_content_type == "application/pdf":
        return TASK_RUN_PDF_ARTIFACT_MAX_SIZE_BYTES

    return TASK_RUN_ARTIFACT_MAX_SIZE_BYTES


def build_task_run_artifact_size_error(
    artifact_name: str | None,
    max_size_bytes: int,
) -> str:
    max_mb = max_size_bytes // (1024 * 1024)

    if (artifact_name or "").lower().endswith(".pdf"):
        return f"{artifact_name or 'Artifact'} exceeds the {max_mb}MB attachment limit for PDFs in cloud runs"

    return f"{artifact_name or 'Artifact'} exceeds the {max_mb}MB attachment limit"


class TaskSerializer(serializers.ModelSerializer):
    repository = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    latest_run = serializers.SerializerMethodField()
    created_by = UserBasicSerializer(read_only=True)

    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    origin_product = serializers.ChoiceField(choices=Task.OriginProduct.choices, required=False)
    # Write-only: which SignalReportTask row to create when linking a task to a report from the
    # public task API (e.g. PostHog Code inbox). Only implementation is supported; research/repo
    # selection links are created by server-side flows.
    signal_report_task_relationship = serializers.ChoiceField(
        choices=[
            (
                SignalReportTask.Relationship.IMPLEMENTATION.value,
                SignalReportTask.Relationship.IMPLEMENTATION.label,
            ),
        ],
        required=False,
        write_only=True,
    )

    class Meta:
        model = Task
        fields = [
            "id",
            "task_number",
            "slug",
            "title",
            "title_manually_set",
            "description",
            "origin_product",
            "repository",
            "github_integration",
            "signal_report",
            "signal_report_task_relationship",
            "json_schema",
            "internal",
            "latest_run",
            "created_at",
            "updated_at",
            "created_by",
            "ci_prompt",
        ]
        read_only_fields = [
            "id",
            "task_number",
            "slug",
            "created_at",
            "updated_at",
            "created_by",
            "latest_run",
        ]

    @extend_schema_field(serializers.DictField(allow_null=True, help_text="Latest run details for this task"))
    def get_latest_run(self, obj):
        latest_run = obj.latest_run
        if latest_run:
            return TaskRunDetailSerializer(latest_run, context=self.context).data
        return None

    def validate_github_integration(self, value):
        """Validate that the GitHub integration belongs to the same team"""
        if value and value.team_id != self.context["team"].id:
            raise serializers.ValidationError("Integration must belong to the same team")
        return value

    def validate_repository(self, value):
        """Validate repository configuration"""
        if not value:
            return value

        parts = value.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise serializers.ValidationError("Repository must be in the format organization/repository")

        return value.lower()

    def validate_signal_report(self, value):
        if value and value.team_id != self.context["team"].id:
            raise serializers.ValidationError("Signal report must belong to the same team")
        return value

    def validate(self, attrs: dict) -> dict:
        rel = attrs.get("signal_report_task_relationship")
        if rel is not None:
            if not attrs.get("signal_report"):
                raise serializers.ValidationError(
                    {"signal_report_task_relationship": "Requires signal_report when set."}
                )
            if attrs.get("origin_product") != Task.OriginProduct.SIGNAL_REPORT:
                raise serializers.ValidationError(
                    {"signal_report_task_relationship": ("Requires origin_product signal_report when set.")}
                )
        return attrs

    def create(self, validated_data):
        validated_data["team"] = self.context["team"]

        if "request" in self.context and hasattr(self.context["request"], "user"):
            validated_data["created_by"] = self.context["request"].user

        link_relationship = validated_data.pop(
            "signal_report_task_relationship",
            SignalReportTask.Relationship.IMPLEMENTATION,
        )

        # Set default GitHub integration if not provided
        if not validated_data.get("github_integration"):
            default_integration = Integration.objects.filter(team=self.context["team"], kind="github").first()
            if default_integration:
                validated_data["github_integration"] = default_integration

        title = validated_data.get("title", "").strip()
        if not title and validated_data.get("description"):
            validated_data["title"] = generate_task_title(validated_data["description"])
            validated_data.setdefault("title_manually_set", False)
        elif title:
            validated_data.setdefault("title_manually_set", True)

        # Inbox / PostHog Code: tasks created via this API with a signal report use the same
        # origin_product as server-side flows, but only those flows previously called
        # SignalReportTask.objects.create. Link implementation tasks here so report task
        # listings (e.g. getSignalReportTasks) match autostarted implementations.
        with transaction.atomic():
            task = super().create(validated_data)
            if task.signal_report_id and task.origin_product == Task.OriginProduct.SIGNAL_REPORT:
                SignalReportTask.objects.create(
                    team_id=task.team_id,
                    report_id=task.signal_report_id,
                    task=task,
                    relationship=link_relationship,
                )
            return task

    def update(self, instance, validated_data):
        if "title" in validated_data and "title_manually_set" not in validated_data:
            validated_data["title_manually_set"] = True
        return super().update(instance, validated_data)


class AgentDefinitionSerializer(serializers.Serializer):
    """Serializer for agent definitions"""

    id = serializers.CharField()
    name = serializers.CharField()
    agent_type = serializers.CharField()
    description = serializers.CharField()
    config = serializers.DictField(default=dict)
    is_active = serializers.BooleanField(default=True)


class TaskRunUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=["not_started", "queued", "in_progress", "completed", "failed", "cancelled"],
        required=False,
        help_text="Current execution status",
    )
    branch = serializers.CharField(
        required=False, allow_null=True, help_text="Git branch name to associate with the task"
    )
    stage = serializers.CharField(
        required=False, allow_null=True, help_text="Current stage of the run (e.g. research, plan, build)"
    )
    output = serializers.JSONField(required=False, allow_null=True, help_text="Output from the run")
    state = serializers.JSONField(required=False, help_text="State of the run")
    state_remove_keys = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=False,
        help_text="State keys to remove atomically before applying any state updates.",
    )
    error_message = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, help_text="Error message if execution failed"
    )


class TaskRunArtifactResponseSerializer(serializers.Serializer):
    id = serializers.CharField(required=False, help_text="Stable identifier for the artifact within this run")
    name = serializers.CharField(help_text="Artifact file name")
    type = serializers.CharField(help_text="Artifact classification (plan, context, etc.)")
    source = serializers.CharField(  # type: ignore[assignment]
        required=False,
        allow_blank=True,
        help_text="Source of the artifact, such as agent_output or user_attachment",
    )
    size = serializers.IntegerField(required=False, help_text="Artifact size in bytes")
    content_type = serializers.CharField(required=False, allow_blank=True, help_text="Optional MIME type")
    storage_path = serializers.CharField(help_text="S3 object key for the artifact")
    uploaded_at = serializers.CharField(help_text="Timestamp when the artifact was uploaded")


class TaskRunDetailSerializer(serializers.ModelSerializer):
    _run_state_cache: dict[str, RunState]

    log_url = serializers.SerializerMethodField(help_text="Presigned S3 URL for log access (valid for 1 hour).")
    artifacts = TaskRunArtifactResponseSerializer(many=True, read_only=True)
    runtime_adapter = serializers.SerializerMethodField(
        help_text="Configured runtime adapter for this run, such as 'claude' or 'codex'."
    )
    provider = serializers.SerializerMethodField(
        help_text="Configured LLM provider for this run, such as 'anthropic' or 'openai'."
    )
    model = serializers.SerializerMethodField(help_text="Configured LLM model identifier for this run.")
    reasoning_effort = serializers.SerializerMethodField(
        help_text="Configured reasoning effort for this run when the selected model supports it."
    )

    class Meta:
        model = TaskRun
        fields = [
            "id",
            "task",
            "stage",
            "branch",
            "status",
            "environment",
            "runtime_adapter",
            "provider",
            "model",
            "reasoning_effort",
            "log_url",
            "error_message",
            "output",
            "state",
            "artifacts",
            "created_at",
            "updated_at",
            "completed_at",
        ]
        read_only_fields = [
            "id",
            "task",
            "log_url",
            "created_at",
            "updated_at",
            "completed_at",
        ]

    @extend_schema_field(
        serializers.URLField(allow_null=True, help_text="Presigned S3 URL for log access (valid for 1 hour).")
    )
    def get_log_url(self, obj: TaskRun) -> str | None:
        """Return presigned S3 URL for log access, cached to avoid regeneration."""
        cache_key = f"task_run_log_url:{obj.id}"

        cached_url = cache.get(cache_key)
        if cached_url:
            return cached_url

        presigned_url = object_storage.get_presigned_url(obj.log_url, expiration=3600)

        if presigned_url:
            cache.set(cache_key, presigned_url, timeout=PRESIGNED_URL_CACHE_TTL)

        return presigned_url

    def _get_run_state(self, obj: TaskRun) -> RunState:
        if not hasattr(self, "_run_state_cache"):
            self._run_state_cache = {}

        cache_key = str(obj.id)
        cached_state = self._run_state_cache.get(cache_key)
        if cached_state is not None:
            return cached_state

        parsed_state = parse_run_state(obj.state)
        self._run_state_cache[cache_key] = parsed_state
        return parsed_state

    @extend_schema_field(
        serializers.ChoiceField(
            choices=[adapter.value for adapter in RuntimeAdapter],
            allow_null=True,
            help_text="Configured runtime adapter for this run, such as 'claude' or 'codex'.",
        )
    )
    def get_runtime_adapter(self, obj: TaskRun) -> str | None:
        state = self._get_run_state(obj)
        return state.runtime_adapter.value if state.runtime_adapter is not None else None

    @extend_schema_field(
        serializers.ChoiceField(
            choices=[provider.value for provider in LLMProvider],
            allow_null=True,
            help_text="Configured LLM provider for this run, such as 'anthropic' or 'openai'.",
        )
    )
    def get_provider(self, obj: TaskRun) -> str | None:
        state = self._get_run_state(obj)
        return state.provider.value if state.provider is not None else None

    @extend_schema_field(
        serializers.CharField(allow_null=True, help_text="Configured LLM model identifier for this run.")
    )
    def get_model(self, obj: TaskRun) -> str | None:
        return self._get_run_state(obj).model

    @extend_schema_field(
        serializers.ChoiceField(
            choices=[effort.value for effort in PUBLIC_REASONING_EFFORTS],
            allow_null=True,
            help_text="Configured reasoning effort for this run when the selected model supports it.",
        )
    )
    def get_reasoning_effort(self, obj: TaskRun) -> str | None:
        state = self._get_run_state(obj)
        return state.reasoning_effort.value if state.reasoning_effort is not None else None

    def validate_task(self, value):
        team = self.context.get("team")
        if team and value.team_id != team.id:
            raise serializers.ValidationError("Task must belong to the same team")
        return value

    def create(self, validated_data):
        validated_data["team"] = self.context["team"]
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Never allow task reassignment through updates
        validated_data.pop("task", None)

        status = validated_data.get("status")
        if status in [TaskRun.Status.COMPLETED, TaskRun.Status.FAILED] and not validated_data.get("completed_at"):
            validated_data["completed_at"] = timezone.now()
        return super().update(instance, validated_data)


class TaskRunSetOutputRequestSerializer(serializers.Serializer):
    output = serializers.JSONField(
        help_text="Output data from the run. Validated against the task's json_schema if one is set."
    )


class ErrorResponseSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="Error message")


class AgentListResponseSerializer(serializers.Serializer):
    results = AgentDefinitionSerializer(many=True, help_text="Array of available agent definitions")


class TaskRunAppendLogRequestSerializer(serializers.Serializer):
    entries = serializers.ListField(
        child=serializers.DictField(),
        help_text="Array of log entry dictionaries to append",
    )

    def validate_entries(self, value):
        """Validate that entries is a non-empty list of dicts"""
        if not value:
            raise serializers.ValidationError("At least one log entry is required")
        return value


class TaskRunRelayMessageResponseSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="Relay status: 'accepted' or 'skipped'")
    relay_id = serializers.CharField(required=False, help_text="Relay workflow ID when accepted")


class TaskRunRelayMessageRequestSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=10000)


class TaskRunArtifactUploadSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="File name to associate with the artifact")
    type = serializers.ChoiceField(choices=TASK_RUN_ARTIFACT_TYPE_CHOICES, help_text="Classification for the artifact")
    source = serializers.CharField(  # type: ignore[assignment]
        max_length=64,
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional source label for the artifact, such as agent_output or user_attachment",
    )
    content = serializers.CharField(help_text="Artifact contents encoded according to content_encoding")
    content_encoding = serializers.ChoiceField(
        choices=TASK_RUN_ARTIFACT_CONTENT_ENCODING_CHOICES,
        required=False,
        default="utf-8",
        help_text="Encoding used for content. Use base64 for binary files and utf-8 for text payloads.",
    )
    content_type = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="Optional MIME type for the artifact",
    )

    def validate(self, attrs):
        content = attrs["content"]
        content_encoding = attrs.get("content_encoding", "utf-8")

        if content_encoding == "base64":
            try:
                attrs["content_bytes"] = base64.b64decode(content, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise serializers.ValidationError({"content": "Invalid base64 content"}) from exc
        else:
            attrs["content_bytes"] = content.encode("utf-8")

        max_size_bytes = get_task_run_artifact_max_size_bytes(
            attrs.get("name"),
            attrs.get("content_type"),
            attrs.get("type"),
        )
        if len(attrs["content_bytes"]) > max_size_bytes:
            raise serializers.ValidationError(
                {"content": build_task_run_artifact_size_error(attrs.get("name"), max_size_bytes)}
            )

        return attrs


class TaskRunArtifactsUploadRequestSerializer(serializers.Serializer):
    artifacts = TaskRunArtifactUploadSerializer(many=True, help_text="Array of artifacts to upload")

    def validate_artifacts(self, value):
        if not value:
            raise serializers.ValidationError("At least one artifact is required")
        return value


class TaskRunArtifactsUploadResponseSerializer(serializers.Serializer):
    artifacts = TaskRunArtifactResponseSerializer(many=True, help_text="Updated list of artifacts on the run")


class TaskRunArtifactPrepareUploadSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="File name to associate with the artifact")
    type = serializers.ChoiceField(choices=TASK_RUN_ARTIFACT_TYPE_CHOICES, help_text="Classification for the artifact")
    source = serializers.CharField(  # type: ignore[assignment]
        max_length=64,
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional source label for the artifact, such as agent_output or user_attachment",
    )
    size = serializers.IntegerField(
        min_value=1,
        max_value=TASK_RUN_ARTIFACT_MAX_SIZE_BYTES,
        help_text=f"Expected upload size in bytes (max {TASK_RUN_ARTIFACT_MAX_SIZE_BYTES} bytes)",
    )
    content_type = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="Optional MIME type for the artifact upload",
    )

    def validate(self, attrs):
        max_size_bytes = get_task_run_artifact_max_size_bytes(
            attrs.get("name"),
            attrs.get("content_type"),
            attrs.get("type"),
        )
        if attrs["size"] > max_size_bytes:
            raise serializers.ValidationError(
                {"size": build_task_run_artifact_size_error(attrs.get("name"), max_size_bytes)}
            )
        return attrs


class TaskRunArtifactsPrepareUploadRequestSerializer(serializers.Serializer):
    artifacts = TaskRunArtifactPrepareUploadSerializer(many=True, help_text="Array of artifacts to prepare")

    def validate_artifacts(self, value):
        if not value:
            raise serializers.ValidationError("At least one artifact is required")
        return value


class S3PresignedPostSerializer(serializers.Serializer):
    url = serializers.URLField(help_text="Presigned S3 POST URL")
    fields = serializers.DictField(  # type: ignore[assignment]
        child=serializers.CharField(),
        help_text="Form fields that must be submitted verbatim with the file upload",
    )


class TaskRunArtifactPrepareUploadResponseSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Stable identifier for the prepared artifact within this run")
    name = serializers.CharField(help_text="Artifact file name")
    type = serializers.CharField(help_text="Artifact classification (plan, context, etc.)")
    source = serializers.CharField(  # type: ignore[assignment]
        required=False,
        allow_blank=True,
        help_text="Source of the artifact, such as agent_output or user_attachment",
    )
    size = serializers.IntegerField(help_text="Expected upload size in bytes")
    content_type = serializers.CharField(required=False, allow_blank=True, help_text="Optional MIME type")
    storage_path = serializers.CharField(help_text="S3 object key reserved for the artifact")
    expires_in = serializers.IntegerField(help_text="Presigned POST expiry in seconds")
    presigned_post = S3PresignedPostSerializer(help_text="Presigned S3 POST configuration for uploading the file")


class TaskRunArtifactsPrepareUploadResponseSerializer(serializers.Serializer):
    artifacts = TaskRunArtifactPrepareUploadResponseSerializer(
        many=True, help_text="Prepared uploads for the requested artifacts"
    )


class TaskRunArtifactFinalizeUploadSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Stable identifier returned by the prepare upload endpoint")
    name = serializers.CharField(max_length=255, help_text="File name associated with the artifact")
    type = serializers.ChoiceField(choices=TASK_RUN_ARTIFACT_TYPE_CHOICES, help_text="Classification for the artifact")
    source = serializers.CharField(  # type: ignore[assignment]
        max_length=64,
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional source label for the artifact, such as agent_output or user_attachment",
    )
    storage_path = serializers.CharField(max_length=500, help_text="S3 object key returned by the prepare step")
    content_type = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="Optional MIME type recorded for the artifact",
    )


class TaskRunArtifactsFinalizeUploadRequestSerializer(serializers.Serializer):
    artifacts = TaskRunArtifactFinalizeUploadSerializer(many=True, help_text="Array of uploaded artifacts to finalize")

    def validate_artifacts(self, value):
        if not value:
            raise serializers.ValidationError("At least one artifact is required")
        return value


class TaskRunArtifactsFinalizeUploadResponseSerializer(serializers.Serializer):
    artifacts = TaskRunArtifactResponseSerializer(many=True, help_text="Updated list of artifacts on the run")


class TaskStagedArtifactPrepareUploadSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="File name to associate with the staged artifact")
    type = serializers.ChoiceField(choices=TASK_RUN_ARTIFACT_TYPE_CHOICES, help_text="Classification for the artifact")
    source = serializers.CharField(  # type: ignore[assignment]
        max_length=64,
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional source label for the artifact, such as agent_output or user_attachment",
    )
    size = serializers.IntegerField(
        min_value=1,
        max_value=TASK_RUN_ARTIFACT_MAX_SIZE_BYTES,
        help_text=f"Expected upload size in bytes (max {TASK_RUN_ARTIFACT_MAX_SIZE_BYTES} bytes)",
    )
    content_type = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="Optional MIME type for the artifact upload",
    )

    def validate(self, attrs):
        max_size_bytes = get_task_run_artifact_max_size_bytes(
            attrs.get("name"),
            attrs.get("content_type"),
            attrs.get("type"),
        )
        if attrs["size"] > max_size_bytes:
            raise serializers.ValidationError(
                {"size": build_task_run_artifact_size_error(attrs.get("name"), max_size_bytes)}
            )
        return attrs


class TaskStagedArtifactsPrepareUploadRequestSerializer(serializers.Serializer):
    artifacts = TaskStagedArtifactPrepareUploadSerializer(
        many=True, help_text="Array of staged artifacts to prepare before creating a run"
    )

    def validate_artifacts(self, value):
        if not value:
            raise serializers.ValidationError("At least one artifact is required")
        return value


class TaskStagedArtifactPrepareUploadResponseSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Stable identifier for the prepared staged artifact within this task")
    name = serializers.CharField(help_text="Artifact file name")
    type = serializers.CharField(help_text="Artifact classification (plan, context, etc.)")
    source = serializers.CharField(  # type: ignore[assignment]
        required=False,
        allow_blank=True,
        help_text="Source of the artifact, such as agent_output or user_attachment",
    )
    size = serializers.IntegerField(help_text="Expected upload size in bytes")
    content_type = serializers.CharField(required=False, allow_blank=True, help_text="Optional MIME type")
    storage_path = serializers.CharField(help_text="S3 object key reserved for the staged artifact")
    expires_in = serializers.IntegerField(help_text="Presigned POST expiry in seconds")
    presigned_post = S3PresignedPostSerializer(help_text="Presigned S3 POST configuration for uploading the file")


class TaskStagedArtifactsPrepareUploadResponseSerializer(serializers.Serializer):
    artifacts = TaskStagedArtifactPrepareUploadResponseSerializer(
        many=True, help_text="Prepared staged uploads for the requested artifacts"
    )


class TaskStagedArtifactFinalizeUploadSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Stable identifier returned by the staged prepare upload endpoint")
    name = serializers.CharField(max_length=255, help_text="File name associated with the staged artifact")
    type = serializers.ChoiceField(choices=TASK_RUN_ARTIFACT_TYPE_CHOICES, help_text="Classification for the artifact")
    source = serializers.CharField(  # type: ignore[assignment]
        max_length=64,
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional source label for the artifact, such as agent_output or user_attachment",
    )
    storage_path = serializers.CharField(max_length=500, help_text="S3 object key returned by the prepare step")
    content_type = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="Optional MIME type recorded for the artifact",
    )


class TaskStagedArtifactsFinalizeUploadRequestSerializer(serializers.Serializer):
    artifacts = TaskStagedArtifactFinalizeUploadSerializer(
        many=True, help_text="Array of staged artifacts to finalize after upload"
    )

    def validate_artifacts(self, value):
        if not value:
            raise serializers.ValidationError("At least one artifact is required")
        return value


class TaskStagedArtifactsFinalizeUploadResponseSerializer(serializers.Serializer):
    artifacts = TaskRunArtifactResponseSerializer(
        many=True, help_text="Finalized staged artifacts available for attachment to a new run"
    )


class TaskRunArtifactPresignRequestSerializer(serializers.Serializer):
    storage_path = serializers.CharField(
        max_length=500,
        help_text="S3 storage path returned in the artifact manifest",
    )


class TaskRunArtifactPresignResponseSerializer(serializers.Serializer):
    url = serializers.URLField(help_text="Presigned URL for downloading the artifact")
    expires_in = serializers.IntegerField(help_text="URL expiry in seconds")


class TaskListQuerySerializer(serializers.Serializer):
    """Query parameters for listing tasks"""

    origin_product = serializers.CharField(required=False, help_text="Filter by origin product")
    stage = serializers.CharField(required=False, help_text="Filter by task run stage")
    organization = serializers.CharField(required=False, help_text="Filter by repository organization")
    repository = serializers.CharField(
        required=False, help_text="Filter by repository name (can include org/repo format)"
    )
    created_by = serializers.IntegerField(required=False, help_text="Filter by creator user ID")
    internal = serializers.BooleanField(
        required=False, help_text="Filter by internal flag. Defaults to excluding internal tasks when not specified."
    )


class RepositoryReadinessQuerySerializer(serializers.Serializer):
    repository = serializers.CharField(required=True, help_text="Repository in org/repo format")
    window_days = serializers.IntegerField(required=False, default=7, min_value=1, max_value=30)
    refresh = serializers.BooleanField(required=False, default=False)

    def validate_repository(self, value: str) -> str:
        normalized = value.strip().lower()
        parts = normalized.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise serializers.ValidationError("Repository must be in the format organization/repository")
        return normalized


class CapabilityStateSerializer(serializers.Serializer):
    state = serializers.ChoiceField(
        choices=["needs_setup", "detected", "waiting_for_data", "ready", "not_applicable", "unknown"],
        help_text="Current state of the capability",
    )
    estimated = serializers.BooleanField(help_text="Whether the state is estimated from static analysis")
    reason = serializers.CharField(help_text="Human-readable explanation")
    evidence = serializers.DictField(required=False, default=dict, help_text="Supporting evidence")


class ScanEvidenceSerializer(serializers.Serializer):
    filesScanned = serializers.IntegerField(help_text="Number of files scanned")
    detectedFilesCount = serializers.IntegerField(help_text="Total candidate files detected")
    eventNameCount = serializers.IntegerField(help_text="Number of distinct event names found")
    foundPosthogInit = serializers.BooleanField(help_text="Whether posthog.init() was found in scanned files")
    foundPosthogCapture = serializers.BooleanField(help_text="Whether posthog.capture() was found in scanned files")
    foundErrorSignal = serializers.BooleanField(help_text="Whether error tracking signals were found in scanned files")


class RepositoryReadinessResponseSerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Normalized repository identifier")
    classification = serializers.CharField(help_text="Repository classification")
    excluded = serializers.BooleanField(help_text="Whether the repository is excluded from readiness checks")
    coreSuggestions = CapabilityStateSerializer(help_text="Tracking capability state")
    replayInsights = CapabilityStateSerializer(help_text="Computer vision capability state")
    errorInsights = CapabilityStateSerializer(help_text="Error tracking capability state")
    overall = serializers.CharField(help_text="Overall readiness state")
    evidenceTaskCount = serializers.IntegerField(help_text="Count of replay-derived evidence tasks")
    windowDays = serializers.IntegerField(help_text="Lookback window in days")
    generatedAt = serializers.CharField(help_text="ISO timestamp when the response was generated")
    cacheAgeSeconds = serializers.IntegerField(help_text="Age of cached response in seconds")
    scan = ScanEvidenceSerializer(required=False, help_text="Scan evidence details")


class ConnectionTokenResponseSerializer(serializers.Serializer):
    """Response containing a JWT token for direct sandbox connection"""

    token = serializers.CharField(help_text="JWT token for authenticating with the sandbox")


class TaskRunCreateRequestSerializer(serializers.Serializer):
    """Request body for creating a new task run"""

    PR_AUTHORSHIP_MODE_CHOICES = [mode.value for mode in PrAuthorshipMode]
    RUN_SOURCE_CHOICES = [source.value for source in RunSource]
    RUNTIME_ADAPTER_CHOICES = [adapter.value for adapter in RuntimeAdapter]
    REASONING_EFFORT_CHOICES = [effort.value for effort in PUBLIC_REASONING_EFFORTS]

    mode = serializers.ChoiceField(
        choices=["interactive", "background"],
        required=False,
        default="background",
        help_text="Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs",
    )
    branch = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        max_length=255,
        help_text="Git branch to checkout in the sandbox",
    )
    resume_from_run_id = serializers.UUIDField(
        required=False,
        default=None,
        help_text="ID of a previous run to resume from. Must belong to the same task.",
    )
    pending_user_message = serializers.CharField(
        required=False,
        default=None,
        allow_blank=True,
        help_text="Initial or follow-up user message to include in the run prompt.",
    )
    pending_user_artifact_ids = serializers.ListField(
        required=False,
        default=list,
        child=serializers.CharField(max_length=128),
        help_text="Identifiers for staged task artifacts that should be attached to the initial run prompt.",
    )
    sandbox_environment_id = serializers.UUIDField(
        required=False,
        default=None,
        help_text="Optional sandbox environment to apply for this cloud run.",
    )
    pr_authorship_mode = serializers.ChoiceField(
        choices=PR_AUTHORSHIP_MODE_CHOICES,
        required=False,
        default=None,
        help_text="Whether pull requests for this run should be authored by the user or the bot.",
    )
    run_source = serializers.ChoiceField(
        choices=RUN_SOURCE_CHOICES,
        required=False,
        default=None,
        help_text="High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.",
    )
    signal_report_id = serializers.CharField(
        required=False,
        default=None,
        allow_blank=False,
        help_text="Optional signal report identifier when this run was started from Inbox.",
    )
    runtime_adapter = serializers.ChoiceField(
        choices=RUNTIME_ADAPTER_CHOICES,
        required=False,
        default=None,
        help_text="Agent runtime adapter to launch for this run. Use 'claude' for the Claude runtime or 'codex' for the Codex runtime.",
    )
    model = serializers.CharField(
        required=False,
        default=None,
        allow_blank=False,
        help_text="LLM model identifier to run in the selected runtime.",
    )
    reasoning_effort = serializers.ChoiceField(
        choices=REASONING_EFFORT_CHOICES,
        required=False,
        default=None,
        help_text="Reasoning effort to request for models that expose an effort control.",
    )
    github_user_token = serializers.CharField(
        required=False,
        default=None,
        allow_blank=False,
        write_only=True,
        help_text="Ephemeral GitHub user token from PostHog Code for user-authored cloud pull requests.",
    )
    initial_permission_mode = serializers.ChoiceField(
        choices=ALL_INITIAL_PERMISSION_MODE_CHOICES,
        required=False,
        default=None,
        help_text=(
            "Initial permission mode for the agent session. Claude runtimes accept "
            "'default', 'acceptEdits', 'plan', 'bypassPermissions', and 'auto'. "
            "Codex runtimes accept 'auto', 'read-only', and 'full-access'."
        ),
    )

    def validate(self, attrs):
        errors: dict[str, str] = {}
        initial_permission_mode = attrs.get("initial_permission_mode")
        runtime_adapter = attrs.get("runtime_adapter")
        if initial_permission_mode is not None:
            if runtime_adapter is None:
                errors["initial_permission_mode"] = "This field requires runtime_adapter to be set."
            else:
                allowed_permission_modes = (
                    list(CODEX_INITIAL_PERMISSION_MODE_CHOICES)
                    if runtime_adapter == RuntimeAdapter.CODEX.value
                    else list(INITIAL_PERMISSION_MODE_CHOICES)
                )

                if initial_permission_mode not in allowed_permission_modes:
                    allowed_values = ", ".join(f"'{value}'" for value in allowed_permission_modes)
                    errors["initial_permission_mode"] = (
                        f"Invalid choice '{initial_permission_mode}' for runtime_adapter "
                        f"'{runtime_adapter}'. Supported values: {allowed_values}."
                    )

        pending_user_message = attrs.get("pending_user_message")
        pending_user_artifact_ids = attrs.get("pending_user_artifact_ids") or []
        if pending_user_message is not None:
            trimmed_message = pending_user_message.strip()
            attrs["pending_user_message"] = trimmed_message or None
        if not attrs.get("pending_user_message") and not pending_user_artifact_ids:
            attrs.pop("pending_user_message", None)

        runtime_fields = ("runtime_adapter", "model")
        has_runtime_selection = any(attrs.get(field) is not None for field in (*runtime_fields, "reasoning_effort"))

        if not has_runtime_selection:
            if errors:
                raise serializers.ValidationError(errors)
            return attrs

        for field in runtime_fields:
            if attrs.get(field) is None:
                errors[field] = "This field is required when selecting a cloud runtime."

        reasoning_effort_error = get_reasoning_effort_error(
            runtime_adapter=attrs.get("runtime_adapter"),
            model=attrs.get("model"),
            reasoning_effort=attrs.get("reasoning_effort"),
        )
        if reasoning_effort_error is not None:
            errors["reasoning_effort"] = reasoning_effort_error

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class TaskRunBootstrapCreateRequestSerializer(serializers.Serializer):
    """Request body for creating a task run without starting execution yet."""

    PR_AUTHORSHIP_MODE_CHOICES = [mode.value for mode in PrAuthorshipMode]
    RUN_SOURCE_CHOICES = [source.value for source in RunSource]
    RUNTIME_ADAPTER_CHOICES = [adapter.value for adapter in RuntimeAdapter]
    REASONING_EFFORT_CHOICES = [effort.value for effort in PUBLIC_REASONING_EFFORTS]

    environment = serializers.ChoiceField(
        choices=[environment.value for environment in TaskRun.Environment],
        required=False,
        default=TaskRun.Environment.LOCAL,
        help_text="Execution environment for the new run. Use 'cloud' for remote sandbox runs and 'local' for desktop sessions.",
    )
    mode = serializers.ChoiceField(
        choices=["interactive", "background"],
        required=False,
        default="background",
        help_text="Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs",
    )
    branch = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        max_length=255,
        help_text="Git branch to checkout in the sandbox",
    )
    sandbox_environment_id = serializers.UUIDField(
        required=False,
        default=None,
        help_text="Optional sandbox environment to apply for this cloud run.",
    )
    pr_authorship_mode = serializers.ChoiceField(
        choices=PR_AUTHORSHIP_MODE_CHOICES,
        required=False,
        default=None,
        help_text="Whether pull requests for this run should be authored by the user or the bot.",
    )
    run_source = serializers.ChoiceField(
        choices=RUN_SOURCE_CHOICES,
        required=False,
        default=None,
        help_text="High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.",
    )
    signal_report_id = serializers.CharField(
        required=False,
        default=None,
        allow_blank=False,
        help_text="Optional signal report identifier when this run was started from Inbox.",
    )
    runtime_adapter = serializers.ChoiceField(
        choices=RUNTIME_ADAPTER_CHOICES,
        required=False,
        default=None,
        help_text="Agent runtime adapter to launch for this run. Use 'claude' for the Claude runtime or 'codex' for the Codex runtime.",
    )
    model = serializers.CharField(
        required=False,
        default=None,
        allow_blank=False,
        help_text="LLM model identifier to run in the selected runtime.",
    )
    reasoning_effort = serializers.ChoiceField(
        choices=REASONING_EFFORT_CHOICES,
        required=False,
        default=None,
        help_text="Reasoning effort to request for models that expose an effort control.",
    )
    github_user_token = serializers.CharField(
        required=False,
        default=None,
        allow_blank=False,
        write_only=True,
        help_text="Ephemeral GitHub user token from PostHog Code for user-authored cloud pull requests.",
    )
    initial_permission_mode = serializers.ChoiceField(
        choices=ALL_INITIAL_PERMISSION_MODE_CHOICES,
        required=False,
        default=None,
        help_text=(
            "Initial permission mode for the agent session. Claude runtimes accept PostHog permission "
            "presets like 'plan'. Codex runtimes accept native Codex modes like 'auto' and "
            "'read-only'."
        ),
    )

    def validate(self, attrs):
        errors: dict[str, str] = {}
        initial_permission_mode = attrs.get("initial_permission_mode")
        runtime_adapter = attrs.get("runtime_adapter")
        if initial_permission_mode is not None:
            if runtime_adapter is None:
                errors["initial_permission_mode"] = "This field requires runtime_adapter to be set."
            else:
                allowed_permission_modes = (
                    list(CODEX_INITIAL_PERMISSION_MODE_CHOICES)
                    if runtime_adapter == RuntimeAdapter.CODEX.value
                    else list(INITIAL_PERMISSION_MODE_CHOICES)
                )

                if initial_permission_mode not in allowed_permission_modes:
                    allowed_values = ", ".join(f"'{value}'" for value in allowed_permission_modes)
                    errors["initial_permission_mode"] = (
                        f"Invalid choice '{initial_permission_mode}' for runtime_adapter "
                        f"'{runtime_adapter}'. Supported values: {allowed_values}."
                    )

        runtime_fields = ("runtime_adapter", "model")
        has_runtime_selection = any(attrs.get(field) is not None for field in (*runtime_fields, "reasoning_effort"))
        if not has_runtime_selection:
            if errors:
                raise serializers.ValidationError(errors)
            return attrs

        for field in runtime_fields:
            if attrs.get(field) is None:
                errors[field] = "This field is required when selecting a cloud runtime."

        reasoning_effort_error = get_reasoning_effort_error(
            runtime_adapter=attrs.get("runtime_adapter"),
            model=attrs.get("model"),
            reasoning_effort=attrs.get("reasoning_effort"),
        )
        if reasoning_effort_error is not None:
            errors["reasoning_effort"] = reasoning_effort_error

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class TaskRunStartRequestSerializer(serializers.Serializer):
    pending_user_message = serializers.CharField(
        required=False,
        default=None,
        allow_blank=True,
        help_text="Initial or follow-up user message to include in the run prompt.",
    )
    pending_user_artifact_ids = serializers.ListField(
        required=False,
        default=list,
        child=serializers.CharField(max_length=128),
        help_text="Identifiers for run artifacts that should be attached to the next user message delivered to the sandbox.",
    )

    def validate(self, attrs):
        pending_user_message = attrs.get("pending_user_message")
        if pending_user_message is not None:
            trimmed_message = pending_user_message.strip()
            attrs["pending_user_message"] = trimmed_message or None

        return attrs


class ClaudeTaskRunCreateSchemaSerializer(TaskRunCreateRequestSerializer):
    runtime_adapter = serializers.ChoiceField(
        choices=[RuntimeAdapter.CLAUDE.value],
        required=True,
        help_text="Agent runtime adapter to launch for this run. Must be 'claude' for Claude runtimes.",
    )
    model = serializers.CharField(
        required=True,
        allow_blank=False,
        help_text="LLM model identifier to run in the Claude runtime.",
    )
    initial_permission_mode = serializers.ChoiceField(
        choices=INITIAL_PERMISSION_MODE_CHOICES,
        required=False,
        default=None,
        help_text="Initial permission mode for Claude runtimes.",
    )


class CodexTaskRunCreateSchemaSerializer(TaskRunCreateRequestSerializer):
    runtime_adapter = serializers.ChoiceField(
        choices=[RuntimeAdapter.CODEX.value],
        required=True,
        help_text="Agent runtime adapter to launch for this run. Must be 'codex' for Codex runtimes.",
    )
    model = serializers.CharField(
        required=True,
        allow_blank=False,
        help_text="LLM model identifier to run in the Codex runtime.",
    )
    initial_permission_mode = serializers.ChoiceField(
        choices=CODEX_INITIAL_PERMISSION_MODE_CHOICES,
        required=False,
        default=None,
        help_text="Initial permission mode for Codex runtimes.",
    )


class TaskRunResumeRequestSchemaSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=["interactive", "background"],
        required=False,
        default="background",
        help_text="Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs",
    )
    branch = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        max_length=255,
        help_text="Git branch to checkout in the sandbox",
    )
    resume_from_run_id = serializers.UUIDField(
        required=False,
        default=None,
        help_text="ID of a previous run to resume from. Must belong to the same task.",
    )
    pending_user_message = serializers.CharField(
        required=False,
        default=None,
        allow_blank=False,
        help_text="Initial or follow-up user message to include in the run prompt.",
    )
    sandbox_environment_id = serializers.UUIDField(
        required=False,
        default=None,
        help_text="Optional sandbox environment to apply for this cloud run.",
    )
    pr_authorship_mode = serializers.ChoiceField(
        choices=TaskRunCreateRequestSerializer.PR_AUTHORSHIP_MODE_CHOICES,
        required=False,
        default=None,
        help_text="Whether pull requests for this run should be authored by the user or the bot.",
    )
    run_source = serializers.ChoiceField(
        choices=TaskRunCreateRequestSerializer.RUN_SOURCE_CHOICES,
        required=False,
        default=None,
        help_text="High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.",
    )
    signal_report_id = serializers.CharField(
        required=False,
        default=None,
        allow_blank=False,
        help_text="Optional signal report identifier when this run was started from Inbox.",
    )
    github_user_token = serializers.CharField(
        required=False,
        default=None,
        allow_blank=False,
        write_only=True,
        help_text="Ephemeral GitHub user token from PostHog Code for user-authored cloud pull requests.",
    )


TaskRunCreateRequestSchemaSerializer = PolymorphicProxySerializer(
    component_name="TaskRunCreateRequestSchema",
    serializers=[
        ClaudeTaskRunCreateSchemaSerializer,
        CodexTaskRunCreateSchemaSerializer,
        TaskRunResumeRequestSchemaSerializer,
    ],
    resource_type_field_name=None,
)


class TaskRunCommandRequestSerializer(serializers.Serializer):
    """JSON-RPC request to send a command to the agent server in the sandbox."""

    ALLOWED_METHODS = [
        "user_message",
        "cancel",
        "close",
        "permission_response",
        "set_config_option",
    ]

    jsonrpc = serializers.ChoiceField(
        choices=["2.0"],
        help_text="JSON-RPC version, must be '2.0'",
    )
    method = serializers.ChoiceField(
        choices=ALLOWED_METHODS,
        help_text="Command method to execute on the agent server",
    )
    params = serializers.DictField(
        required=False,
        default=dict,
        help_text="Parameters for the command",
    )
    id = serializers.JSONField(
        required=False,
        default=None,
        help_text="Optional JSON-RPC request ID (string or number)",
    )

    def validate_id(self, value):
        if value is not None and not isinstance(value, (str, int, float)):
            raise serializers.ValidationError("id must be a string or number")
        return value

    @staticmethod
    def _require_nonempty_string(params: dict, key: str) -> None:
        value = params.get(key)
        if not value or not isinstance(value, str) or not value.strip():
            raise serializers.ValidationError({"params": f"{key} is required and must be a non-empty string"})

    def validate(self, attrs):
        method = attrs["method"]
        params = attrs.get("params", {})
        if method == "user_message":
            content = params.get("content")
            artifact_ids = params.get("artifact_ids")

            normalized_content = None
            if content is not None:
                if not isinstance(content, str):
                    raise serializers.ValidationError({"params": "content must be a string when provided"})
                normalized_content = content.strip()
                if normalized_content:
                    params["content"] = normalized_content
                else:
                    params.pop("content", None)

            if artifact_ids is None:
                normalized_artifact_ids: list[str] = []
            elif not isinstance(artifact_ids, list) or not all(
                isinstance(value, str) and value.strip() for value in artifact_ids
            ):
                raise serializers.ValidationError({"params": "artifact_ids must be a list of non-empty strings"})
            else:
                normalized_artifact_ids = [value.strip() for value in artifact_ids]
                params["artifact_ids"] = normalized_artifact_ids

            if not normalized_content and not normalized_artifact_ids:
                raise serializers.ValidationError(
                    {"params": "user_message requires a non-empty content string, artifact_ids, or both"}
                )
        elif method == "permission_response":
            self._require_nonempty_string(params, "requestId")
            self._require_nonempty_string(params, "optionId")
        elif method == "set_config_option":
            self._require_nonempty_string(params, "configId")
            self._require_nonempty_string(params, "value")
        return attrs


class TaskRunCommandResponseSerializer(serializers.Serializer):
    """Response from the agent server command endpoint."""

    jsonrpc = serializers.CharField(help_text="JSON-RPC version")
    id = serializers.JSONField(required=False, default=None, help_text="Request ID echoed back (string or number)")
    result = serializers.DictField(required=False, help_text="Command result on success")
    error = serializers.DictField(required=False, help_text="Error details on failure")


class CodeInviteRedeemRequestSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=50)


class TaskRunSessionLogsQuerySerializer(serializers.Serializer):
    """Query parameters for filtering task run log events"""

    after = serializers.DateTimeField(
        required=False,
        help_text="Only return events after this ISO8601 timestamp",
    )
    event_types = serializers.CharField(
        required=False,
        help_text="Comma-separated list of event types to include",
    )
    exclude_types = serializers.CharField(
        required=False,
        help_text="Comma-separated list of event types to exclude",
    )
    limit = serializers.IntegerField(
        required=False,
        default=1000,
        min_value=1,
        max_value=5000,
        help_text="Maximum number of entries to return (default 1000, max 5000)",
    )
    offset = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text="Zero-based offset into the filtered log entries",
    )


class TaskAutomationSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=255)
    prompt = serializers.CharField()
    repository = serializers.CharField(max_length=255)
    github_integration = TeamScopedPrimaryKeyRelatedField(
        queryset=Integration.objects.filter(kind="github"),
        required=False,
        allow_null=True,
    )
    last_task_id = serializers.SerializerMethodField()
    last_task_run_id = serializers.SerializerMethodField()

    class Meta:
        model = TaskAutomation
        fields = [
            "id",
            "name",
            "prompt",
            "repository",
            "github_integration",
            "cron_expression",
            "timezone",
            "template_id",
            "enabled",
            "last_run_at",
            "last_run_status",
            "last_task_id",
            "last_task_run_id",
            "last_error",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "last_run_at",
            "last_run_status",
            "last_task_id",
            "last_task_run_id",
            "last_error",
            "created_at",
            "updated_at",
        ]

    def get_last_task_id(self, instance: TaskAutomation) -> str | None:
        return str(instance.task_id)

    def get_last_task_run_id(self, instance: TaskAutomation) -> str | None:
        return str(instance.last_task_run_id) if instance.last_task_run_id else None

    def validate_github_integration(self, value):
        if value and value.team_id != self.context["team"].id:
            raise serializers.ValidationError("Integration must belong to the same team")
        return value

    def validate_repository(self, value: str) -> str:
        normalized = value.strip().lower()
        parts = normalized.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise serializers.ValidationError("Repository must be in the format organization/repository")
        return normalized

    def validate_cron_expression(self, value: str) -> str:
        normalized = value.strip()
        parts = normalized.split()
        if len(parts) != 5:
            raise serializers.ValidationError(
                "Only standard 5-field cron expressions are supported "
                "(minute hour day month weekday). Example: '0 9 * * 1-5'."
            )
        if not croniter.is_valid(normalized):
            raise serializers.ValidationError(
                "Invalid cron expression. Use standard 5-field cron syntax (e.g., '0 9 * * 1-5')."
            )
        return normalized

    def validate_timezone(self, value: str) -> str:
        if value not in available_timezones():
            raise serializers.ValidationError(f"'{value}' is not a valid IANA timezone.")
        return value

    def create(self, validated_data):
        if not validated_data.get("github_integration"):
            default_integration = Integration.objects.filter(team=self.context["team"], kind="github").first()
            if default_integration:
                validated_data["github_integration"] = default_integration

        with transaction.atomic():
            task = Task.objects.create(
                team=self.context["team"],
                created_by=self.context["request"].user,
                title=validated_data.pop("name"),
                description=validated_data.pop("prompt"),
                origin_product=Task.OriginProduct.AUTOMATION,
                repository=validated_data.pop("repository"),
                github_integration=validated_data.pop("github_integration", None),
            )
            return TaskAutomation.objects.create(task=task, **validated_data)

    def update(self, instance, validated_data):
        task_fields = {
            "name": "title",
            "prompt": "description",
            "repository": "repository",
            "github_integration": "github_integration",
        }
        task_updates = {}
        for serializer_field, task_field in task_fields.items():
            if serializer_field in validated_data:
                task_updates[task_field] = validated_data.pop(serializer_field)

        with transaction.atomic():
            automation = super().update(instance, validated_data)

            if task_updates:
                task = automation.task
                fields_to_update = []
                for field, value in task_updates.items():
                    if getattr(task, field) != value:
                        setattr(task, field, value)
                        fields_to_update.append(field)
                if fields_to_update:
                    fields_to_update.append("updated_at")
                    task.save(update_fields=fields_to_update)

        return automation


class SandboxEnvironmentSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    effective_domains = serializers.SerializerMethodField(
        help_text="Computed domain allowlist based on network_access_level and allowed_domains"
    )
    environment_variables = serializers.JSONField(
        write_only=True,
        required=False,
        default=dict,
        help_text="Encrypted environment variables (write-only, never returned in responses)",
    )
    has_environment_variables = serializers.SerializerMethodField(
        help_text="Whether this environment has any environment variables set"
    )

    class Meta:
        model = SandboxEnvironment
        fields = [
            "id",
            "name",
            "network_access_level",
            "allowed_domains",
            "include_default_domains",
            "repositories",
            "environment_variables",
            "has_environment_variables",
            "private",
            "internal",
            "effective_domains",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "internal",
            "created_by",
            "created_at",
            "updated_at",
            "effective_domains",
            "has_environment_variables",
        ]

    def get_effective_domains(self, obj: SandboxEnvironment) -> list[str]:
        return obj.get_effective_domains()

    def get_has_environment_variables(self, obj: SandboxEnvironment) -> bool:
        return bool(obj.environment_variables)

    def validate_environment_variables(self, value):
        if value:
            for key in value:
                if not SandboxEnvironment.is_valid_env_var_key(key):
                    raise serializers.ValidationError(
                        f"Invalid environment variable key: {key!r}. Must match [A-Za-z_][A-Za-z0-9_]*"
                    )
        return value

    def create(self, validated_data):
        validated_data["team"] = self.context["team"]
        if "request" in self.context and hasattr(self.context["request"], "user"):
            validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class SandboxEnvironmentListSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = SandboxEnvironment
        fields = [
            "id",
            "name",
            "network_access_level",
            "allowed_domains",
            "repositories",
            "private",
            "internal",
            "created_by",
            "created_at",
            "updated_at",
        ]
