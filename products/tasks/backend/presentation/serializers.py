import base64
import logging
import binascii
from typing import Any, cast
from zoneinfo import available_timezones

import posthoganalytics
from croniter import croniter
from drf_spectacular.utils import PolymorphicProxySerializer
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.event_usage import groups
from posthog.models.integration import Integration
from posthog.models.user_integration import UserIntegration

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import (
    ChannelDTO,
    SandboxCustomImageDTO,
    SandboxEnvironmentDTO,
    TaskAutomationDTO,
    TaskDetailDTO,
    TaskMentionDTO,
    TaskRunDetailDTO,
    TaskSummaryDTO,
    TaskThreadMessageDTO,
    TaskUserBasicInfo,
)
from products.tasks.backend.facade.run_config import (
    ALL_INITIAL_PERMISSION_MODE_CHOICES,
    CODEX_INITIAL_PERMISSION_MODE_CHOICES,
    INITIAL_PERMISSION_MODE_CHOICES,
    PUBLIC_REASONING_EFFORTS,
    LLMProvider,
    PrAuthorshipMode,
    RunSource,
    RuntimeAdapter,
    get_reasoning_effort_error,
)
from products.tasks.backend.models import TaskArtifact

logger = logging.getLogger(__name__)


def _capture_rejected_reasoning_effort(
    context: dict[str, Any],
    *,
    runtime_adapter: str | None,
    model: str | None,
    reasoning_effort: str | None,
    error: str,
) -> None:
    """Record a rejected runtime_adapter/model/reasoning_effort combination server-side.

    This validation only ever reached the caller as a 400 response body, so recurring
    misconfigurations (e.g. a model missing from the supported-effort map) were invisible
    beyond individual client-side error toasts.
    """
    team = context.get("team")
    logger.warning(
        "Rejected task run reasoning_effort/model combination",
        extra={
            "team_id": getattr(team, "id", None),
            "runtime_adapter": runtime_adapter,
            "model": model,
            "reasoning_effort": reasoning_effort,
        },
    )

    request = context.get("request")
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.distinct_id:
        return

    posthoganalytics.capture(
        distinct_id=str(user.distinct_id),
        event="task run reasoning effort rejected",
        properties={
            "runtime_adapter": runtime_adapter,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "error": error,
        },
        groups=groups(team=team),
    )


class TaskUserBasicInfoSerializer(DataclassSerializer):
    """Response shape for a `created_by` user — mirrors core `UserBasicSerializer` output."""

    class Meta:
        dataclass = TaskUserBasicInfo


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
    "skill_bundle",
]
TASK_RUN_ARTIFACT_CONTENT_ENCODING_CHOICES = ["utf-8", "base64"]
TASK_RUN_SKILL_BUNDLE_FORMAT_CHOICES = ["zip"]
TASK_RUN_SKILL_SOURCE_CHOICES = ["user", "repo", "marketplace", "codex"]
TASK_RUN_LIVING_ARTIFACT_TYPE_CHOICES = [choice for choice, _label in TaskArtifact.ArtifactType.choices]
TASK_RUN_LIVING_ARTIFACT_ADAPTER_CHOICES = [choice for choice, _label in TaskArtifact.Adapter.choices]
TASK_RUN_LIVING_ARTIFACT_WRITE_ADAPTER_CHOICES = TASK_RUN_LIVING_ARTIFACT_ADAPTER_CHOICES


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
    environment = serializers.ChoiceField(
        choices=["local"],
        required=False,
        help_text="Transition a cloud run to local. Use the resume_in_cloud action to move a run into cloud.",
    )


class TaskRunArtifactMetadataSerializer(serializers.Serializer):
    skill_name = serializers.CharField(
        allow_blank=False,
        max_length=255,
        help_text="Name of the local skill included in a skill_bundle artifact.",
    )
    skill_source = serializers.ChoiceField(
        choices=TASK_RUN_SKILL_SOURCE_CHOICES,
        help_text="Local source for the uploaded skill bundle, such as user or repo.",
    )
    content_sha256 = serializers.RegexField(
        regex=r"^[a-f0-9]{64}$",
        help_text="SHA-256 hex digest of the uploaded skill bundle bytes.",
    )
    bundle_format = serializers.ChoiceField(
        choices=TASK_RUN_SKILL_BUNDLE_FORMAT_CHOICES,
        help_text="Archive format used for the local skill bundle.",
    )
    schema_version = serializers.IntegerField(
        min_value=1,
        help_text="Version of the local skill bundle metadata schema.",
    )


def validate_task_run_artifact_metadata(attrs: dict[str, Any]) -> dict[str, Any]:
    artifact_type = attrs.get("type")
    metadata = attrs.get("metadata")

    if artifact_type != "skill_bundle":
        return attrs

    if not metadata:
        raise serializers.ValidationError({"metadata": "Skill bundle artifacts require metadata"})

    return attrs


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
    metadata = TaskRunArtifactMetadataSerializer(
        required=False,
        help_text="Optional structured metadata for special artifact types, such as skill bundles.",
    )
    storage_path = serializers.CharField(help_text="S3 object key for the artifact")
    uploaded_at = serializers.CharField(help_text="Timestamp when the artifact was uploaded")


class TaskRunDetailSerializer(DataclassSerializer):
    """Detail response for a task run.

    Reads from a frozen ``TaskRunDetailDTO`` produced by the facade mapper (which computes the
    presigned ``log_url`` and parses ``runtime_adapter`` / ``provider`` / ``model`` /
    ``reasoning_effort`` off the run state). ``task`` is the parent task id. Reused as the nested
    ``latest_run`` shape by the task detail response.
    """

    task = serializers.UUIDField(help_text="Parent task id this run belongs to.")
    log_url = serializers.URLField(
        allow_null=True, required=False, help_text="Presigned S3 URL for log access (valid for 1 hour)."
    )
    artifacts = TaskRunArtifactResponseSerializer(many=True, read_only=True)
    runtime_adapter = serializers.ChoiceField(
        choices=[adapter.value for adapter in RuntimeAdapter],
        allow_null=True,
        required=False,
        help_text="Configured runtime adapter for this run, such as 'claude' or 'codex'.",
    )
    provider = serializers.ChoiceField(
        choices=[provider.value for provider in LLMProvider],
        allow_null=True,
        required=False,
        help_text="Configured LLM provider for this run, such as 'anthropic' or 'openai'.",
    )
    model = serializers.CharField(
        allow_null=True, required=False, help_text="Configured LLM model identifier for this run."
    )
    reasoning_effort = serializers.ChoiceField(
        choices=[effort.value for effort in PUBLIC_REASONING_EFFORTS],
        allow_null=True,
        required=False,
        help_text="Configured reasoning effort for this run when the selected model supports it.",
    )

    class Meta:
        dataclass = TaskRunDetailDTO
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


# Only implementation is supported when linking a task to a report from the public task API
# (e.g. PostHog Code inbox); research/repo-selection links are created by server-side flows.
# Mirrors `signals` `task_run_artefacts.TASK_RUN_TYPE_IMPLEMENTATION` — kept inline
# so presentation never imports the other product's internals.
SIGNAL_REPORT_TASK_RELATIONSHIP_IMPLEMENTATION = "implementation"


class TaskSerializer(DataclassSerializer):
    """Detail response for a task.

    Reads from a frozen ``TaskDetailDTO`` produced by the facade. ``github_integration`` /
    ``github_user_integration`` are integration ids, ``signal_report`` is the report id, and
    ``latest_run`` nests the run-detail shape. ``created_by`` mirrors core ``UserBasicSerializer``.
    """

    latest_run = TaskRunDetailSerializer(allow_null=True, required=False, help_text="Latest run details for this task")
    created_by = TaskUserBasicInfoSerializer(allow_null=True, required=False)

    class Meta:
        dataclass = TaskDetailDTO
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
            "github_user_integration",
            "signal_report",
            "json_schema",
            "internal",
            "archived",
            "archived_at",
            "latest_run",
            "created_at",
            "updated_at",
            "created_by",
            "ci_prompt",
            "channel",
        ]


class TaskWriteSerializer(serializers.Serializer):
    """Request body for creating or updating a task.

    Field required/default semantics match the ``Task`` model. The view passes
    ``validated_data`` (integration/report PK fields already resolved to instances) to the
    facade ``create_task`` / ``update_task`` functions.
    """

    title = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="Short human-readable title. Auto-generated from `description` when omitted.",
    )
    title_manually_set = serializers.BooleanField(
        required=False,
        help_text="Whether the title was set by a human (vs auto-generated from the description).",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Free-form description of the work to be done. Used as the prompt passed to the agent.",
    )
    origin_product = serializers.ChoiceField(
        choices=tasks_facade.TaskOriginProduct.choices,
        required=False,
        help_text="PostHog product or surface that created this task (e.g. error_tracking, slack, user_created).",
    )
    repository = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Target GitHub repository in `organization/repo` format (e.g. `posthog/posthog-js`).",
    )
    github_integration = serializers.PrimaryKeyRelatedField(  # nosemgrep: unscoped-primary-key-related-field
        queryset=Integration.objects.filter(kind="github"),
        required=False,
        allow_null=True,
        help_text="GitHub integration for this task.",
    )
    # UserIntegration is scoped to request.user in validate_github_user_integration.
    github_user_integration = serializers.PrimaryKeyRelatedField(  # nosemgrep: unscoped-primary-key-related-field
        queryset=UserIntegration.objects.filter(kind="github"),
        required=False,
        allow_null=True,
        help_text="User-scoped GitHub integration to use for user-authored cloud runs.",
    )
    # Mirrors the ModelSerializer-generated FK field: queryset is the full report manager
    # (team scope is enforced by validate_signal_report below). Bound lazily in __init__ so
    # importing this module never touches the signals model.
    signal_report = serializers.PrimaryKeyRelatedField(  # nosemgrep: unscoped-primary-key-related-field
        queryset=Integration.objects.none(),
        required=False,
        allow_null=True,
        help_text="Signal report this task implements, when created from a report.",
    )
    # Write-only: which SignalReportTask row to create when linking a task to a report.
    signal_report_task_relationship = serializers.ChoiceField(
        choices=[(SIGNAL_REPORT_TASK_RELATIONSHIP_IMPLEMENTATION, "Implementation")],
        required=False,
        write_only=True,
    )
    json_schema = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text="JSON schema used to validate the output of the task.",
    )
    internal = serializers.BooleanField(
        required=False,
        help_text="If true, this task is for internal use and should not be exposed to end users.",
    )
    archived = serializers.BooleanField(
        required=False,
        help_text="If true, the task is hidden from default list responses.",
    )
    ci_prompt = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Custom prompt for CI fixes. If blank, a default prompt will be used.",
    )
    branch = serializers.CharField(
        max_length=255,
        required=False,
        allow_null=True,
        allow_blank=True,
        write_only=True,
        help_text=(
            "Branch the user has selected for this cloud task. Write-only and not persisted on the "
            "task itself: used only to reuse a matching pre-warmed sandbox Run on creation (the branch "
            "is otherwise carried on the run). Omit to match a warm Run on the default branch."
        ),
    )
    # These three warm-reuse hints are all optional: clients send an explicit
    # null when nothing is selected, so they take allow_null=True (null == "no
    # selection", same as omitting the key — it's read back as None downstream).
    # null and "" are not interchangeable: model keeps allow_blank=False so an
    # empty string, which is never a valid model id, is still rejected.
    runtime_adapter = serializers.ChoiceField(
        choices=[adapter.value for adapter in RuntimeAdapter],
        required=False,
        default=None,
        allow_null=True,
        write_only=True,
        help_text=(
            "Selected runtime adapter ('claude' or 'codex'). Write-only and not persisted on the task: "
            "used only to reuse a pre-warmed Run started on the same runtime. A value differing from the "
            "warm Run's runtime skips reuse so the task isn't silently run on the wrong runtime."
        ),
    )
    model = serializers.CharField(
        required=False,
        default=None,
        allow_blank=False,
        allow_null=True,
        write_only=True,
        help_text="Selected LLM model identifier. Write-only; used only to reuse a warm Run started on the same model.",
    )
    reasoning_effort = serializers.ChoiceField(
        choices=[effort.value for effort in PUBLIC_REASONING_EFFORTS],
        required=False,
        default=None,
        allow_null=True,
        write_only=True,
        help_text="Selected reasoning effort. Write-only; used only to reuse a warm Run started on the same effort.",
    )
    pending_user_message = serializers.CharField(
        required=False,
        default=None,
        allow_null=True,
        allow_blank=True,
        write_only=True,
        help_text=(
            "First user message to forward when creation reuses a pre-warmed Run. Write-only and not "
            "persisted on the task: lets clients deliver a message that differs from `description` "
            "(e.g. a resolved skill invocation with channel context folded in). Ignored when no warm "
            "Run is reused — cold creation takes the first message via the run start endpoint instead."
        ),
    )
    pending_user_artifact_ids = serializers.ListField(
        required=False,
        default=list,
        child=serializers.CharField(max_length=128),
        write_only=True,
        help_text=(
            "Run artifact ids (already uploaded to the pre-warmed Run) to attach to the forwarded "
            "first message when creation reuses that warm Run, e.g. skill bundles or file attachments. "
            "If any id is missing from the warm Run's manifest, warm reuse is skipped and the task is "
            "created cold. Ignored when no warm Run is matched."
        ),
    )
    auto_publish = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        write_only=True,
        help_text=(
            "When true, the cloud run agent pushes its work and opens a draft pull request on "
            "completion without waiting for an explicit ask. Write-only and not persisted on the "
            "task: persisted into the reused warm Run's state when creation activates one, so "
            "resumes of that Run honor it. Ignored when no warm Run is reused — cold creation "
            "takes it via the run start endpoint instead."
        ),
    )
    channel = TeamScopedPrimaryKeyRelatedField(  # nosemgrep: unscoped-primary-key-related-field
        queryset=Integration.objects.none(),
        required=False,
        allow_null=True,
        help_text="Channel this task is owned by (the channel it was kicked off in).",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # SignalReport is scoped to the request team by the field; bind its queryset lazily so
        # importing this module never touches the signals model at import time.
        cast(
            serializers.PrimaryKeyRelatedField, self.fields["signal_report"]
        ).queryset = tasks_facade.signal_report_queryset()
        # Channel queryset comes from the facade so presentation stays off tasks models.
        cast(serializers.PrimaryKeyRelatedField, self.fields["channel"]).queryset = tasks_facade.channel_queryset()

    def validate_channel(self, value):
        """Personal channels are private: only their owner may file tasks into them."""
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if value is not None and value.channel_type == "personal" and value.created_by_id != getattr(user, "id", None):
            raise serializers.ValidationError("Personal channels can only be used by their owner")
        return value

    def validate_github_integration(self, value):
        """Validate that the GitHub integration belongs to the same team"""
        if value and value.team_id != self.context["team"].id:
            raise serializers.ValidationError("Integration must belong to the same team")
        return value

    def validate_github_user_integration(self, value):
        """Validate that the GitHub user integration belongs to the authenticated user."""
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if value and value.user_id != getattr(user, "id", None):
            raise serializers.ValidationError("User integration must belong to the authenticated user")
        return value

    def validate_origin_product(self, value):
        """Reject internal-only origins that are set by server-side flows, never by API callers."""
        if value == tasks_facade.TaskOriginProduct.IMAGE_BUILDER:
            raise serializers.ValidationError("origin_product 'image_builder' is reserved for image-builder sessions")
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
            if attrs.get("origin_product") != tasks_facade.TaskOriginProduct.SIGNAL_REPORT:
                raise serializers.ValidationError(
                    {"signal_report_task_relationship": ("Requires origin_product signal_report when set.")}
                )
        if (
            attrs.get("origin_product") == tasks_facade.TaskOriginProduct.SIGNAL_REPORT
            and attrs.get("github_user_integration") is not None
        ):
            raise serializers.ValidationError(
                {"github_user_integration": "Signal report tasks use the team GitHub integration."}
            )
        return attrs


class TaskRunSetOutputRequestSerializer(serializers.Serializer):
    output = serializers.JSONField(
        help_text="Output data from the run. Validated against the task's json_schema if one is set."
    )


class TaskRunErrorResponseSerializer(serializers.Serializer):
    detail = serializers.CharField(required=False, help_text="Human-readable validation error")
    error = serializers.CharField(required=False, help_text="Human-readable error message")
    type = serializers.CharField(required=False, help_text="Machine-readable error type")
    code = serializers.CharField(required=False, help_text="Machine-readable error code")
    attr = serializers.CharField(required=False, help_text="Request field associated with the error")
    missing_artifact_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Artifact ids that could not be resolved for the run",
    )
    limit_type = serializers.ChoiceField(
        choices=[("burst", "burst"), ("sustained", "sustained")],
        required=False,
        help_text="Which usage limit was hit on a rate_limited error: 'burst' (daily) or 'sustained' (monthly)",
    )
    reset_at = serializers.CharField(
        required=False,
        help_text="ISO 8601 timestamp when the hit usage limit resets, when known",
    )
    is_pro = serializers.BooleanField(
        required=False,
        help_text="Whether the team is on a Pro plan (drives the upgrade-prompt copy)",
    )


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
    text = serializers.CharField(
        max_length=10000,
        help_text="Joined message body. Used when text_parts is absent.",
    )
    # Kept optional for forward/backward compatibility during rollout; will be aligned once deployed.
    text_parts = serializers.ListField(
        child=serializers.CharField(max_length=10000, allow_blank=True),
        required=False,
        allow_empty=True,
        help_text="Ordered assistant text blocks. When present, the last non-empty entry is posted instead of text.",
    )


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
    metadata = TaskRunArtifactMetadataSerializer(
        required=False,
        help_text="Optional structured metadata for special artifact types, such as skill bundles.",
    )

    def validate(self, attrs):
        attrs = validate_task_run_artifact_metadata(attrs)
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


class TaskRunLivingArtifactResponseSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Stable living artifact id. Use this id when editing the artifact.")
    task_id = serializers.CharField(help_text="Task id this living artifact belongs to.")
    run_id = serializers.CharField(help_text="Task run id that created or currently owns this artifact.")
    team_id = serializers.IntegerField(help_text="Project id that owns this artifact.")
    name = serializers.CharField(help_text="Human-readable artifact name.")
    artifact_type = serializers.ChoiceField(
        choices=TASK_RUN_LIVING_ARTIFACT_TYPE_CHOICES,
        help_text="Artifact format or delivery surface, such as document, spreadsheet, slack_canvas, file, or slack_message.",
    )
    adapter = serializers.ChoiceField(
        choices=TASK_RUN_LIVING_ARTIFACT_ADAPTER_CHOICES,
        help_text="Adapter that currently stores or edits the artifact.",
    )
    status = serializers.ChoiceField(
        choices=[choice for choice, _label in TaskArtifact.Status.choices],
        help_text="Current registry status for the artifact.",
    )
    location = serializers.JSONField(help_text="Adapter-specific location, such as S3 key or Slack canvas id.")
    metadata = serializers.JSONField(help_text="Adapter-specific metadata for external storage and source tracking.")
    current_version = serializers.IntegerField(help_text="Current version number for the artifact.")
    versions = serializers.ListField(
        child=serializers.DictField(child=serializers.JSONField()),
        help_text="Chronological version records for this artifact.",
    )
    created_at = serializers.CharField(allow_null=True, required=False, help_text="ISO timestamp when created.")
    updated_at = serializers.CharField(allow_null=True, required=False, help_text="ISO timestamp when last updated.")


class TaskRunLivingArtifactsResponseSerializer(serializers.Serializer):
    artifacts = TaskRunLivingArtifactResponseSerializer(many=True, help_text="Living artifacts for this task run.")


class TaskRunLivingArtifactOpenResponseSerializer(TaskRunLivingArtifactResponseSerializer):
    content = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Current artifact content when the adapter can read it directly.",
    )


class TaskRunLivingArtifactCreateRequestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="Human-readable artifact name, used as the title.")
    artifact_type = serializers.ChoiceField(
        choices=TASK_RUN_LIVING_ARTIFACT_TYPE_CHOICES,
        default=TaskArtifact.ArtifactType.DOCUMENT,
        help_text="Artifact format or delivery surface to create, such as document, spreadsheet, slack_canvas, or file.",
    )
    adapter = serializers.ChoiceField(
        choices=TASK_RUN_LIVING_ARTIFACT_WRITE_ADAPTER_CHOICES,
        required=False,
        help_text="Optional preferred external storage or delivery adapter. Slack adapters deliver into the mapped Slack thread; omitted Slack-run documents use Slack canvas, omitted Slack-run files and spreadsheets use Slack file upload, and document_connector uses a connected external document provider.",
    )
    content = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500000,
        help_text="Markdown or text content for the initial artifact version.",
    )
    content_base64 = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Base64-encoded binary content for Slack file uploads or other external adapters. Prefer source_artifact_id or source_storage_path for large files that were already uploaded as run artifacts.",
    )
    content_type = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="MIME type for content_base64 or source-backed artifacts, such as application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.",
    )
    source_artifact_id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Existing run artifact id to use as the initial content source.",
    )
    source_storage_path = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Existing run artifact storage_path to use as the initial content source.",
    )
    metadata = serializers.DictField(
        child=serializers.JSONField(),
        required=False,
        default=dict,
        help_text="Optional metadata to persist with the living artifact.",
    )

    def validate(self, attrs):
        has_content = bool(attrs.get("content"))
        has_content_base64 = bool(attrs.get("content_base64"))
        has_source = bool(attrs.get("source_artifact_id") or attrs.get("source_storage_path"))
        if sum([has_content, has_content_base64, has_source]) != 1:
            raise serializers.ValidationError(
                {
                    "content": "Provide exactly one of content, content_base64, source_artifact_id, or source_storage_path."
                }
            )
        if has_content_base64:
            try:
                attrs["content_bytes"] = base64.b64decode(attrs["content_base64"], validate=True)
            except (binascii.Error, ValueError) as exc:
                raise serializers.ValidationError({"content_base64": "Invalid base64 content"}) from exc
            attrs.pop("content_base64", None)

            max_size_bytes = get_task_run_artifact_max_size_bytes(
                attrs.get("name"),
                attrs.get("content_type"),
                attrs.get("artifact_type"),
            )
            if len(attrs["content_bytes"]) > max_size_bytes:
                raise serializers.ValidationError(
                    {"content_base64": build_task_run_artifact_size_error(attrs.get("name"), max_size_bytes)}
                )
        return attrs


class TaskRunLivingArtifactEditRequestSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=False,
        help_text="Optional new human-readable artifact name.",
    )
    content = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500000,
        help_text="Markdown or text content for the next version.",
    )
    content_base64 = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Base64-encoded binary content for the next version, used by adapters such as slack_file.",
    )
    content_type = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="MIME type for content_base64 or source-backed edits.",
    )
    source_artifact_id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Existing run artifact id to use as the next version content source.",
    )
    source_storage_path = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Existing run artifact storage_path to use as the next version content source.",
    )
    metadata = serializers.DictField(
        child=serializers.JSONField(),
        required=False,
        default=dict,
        help_text="Optional metadata to merge into the artifact registry record.",
    )

    def validate(self, attrs):
        has_content = "content" in attrs and attrs.get("content") is not None
        has_content_base64 = bool(attrs.get("content_base64"))
        has_source = bool(attrs.get("source_artifact_id") or attrs.get("source_storage_path"))
        if sum([has_content, has_content_base64, has_source]) != 1:
            raise serializers.ValidationError(
                {
                    "content": "Provide exactly one of content, content_base64, source_artifact_id, or source_storage_path."
                }
            )
        if has_content_base64:
            try:
                attrs["content_bytes"] = base64.b64decode(attrs["content_base64"], validate=True)
            except (binascii.Error, ValueError) as exc:
                raise serializers.ValidationError({"content_base64": "Invalid base64 content"}) from exc
            attrs.pop("content_base64", None)

            max_size_bytes = get_task_run_artifact_max_size_bytes(attrs.get("name"), attrs.get("content_type"))
            if len(attrs["content_bytes"]) > max_size_bytes:
                raise serializers.ValidationError(
                    {"content_base64": build_task_run_artifact_size_error(attrs.get("name"), max_size_bytes)}
                )
        return attrs


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
    metadata = TaskRunArtifactMetadataSerializer(
        required=False,
        help_text="Optional structured metadata for special artifact types, such as skill bundles.",
    )

    def validate(self, attrs):
        attrs = validate_task_run_artifact_metadata(attrs)
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
    metadata = TaskRunArtifactMetadataSerializer(
        required=False,
        help_text="Optional structured metadata for special artifact types, such as skill bundles.",
    )
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
    metadata = TaskRunArtifactMetadataSerializer(
        required=False,
        help_text="Optional structured metadata for special artifact types, such as skill bundles.",
    )

    def validate(self, attrs):
        return validate_task_run_artifact_metadata(attrs)


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
    metadata = TaskRunArtifactMetadataSerializer(
        required=False,
        help_text="Optional structured metadata for special artifact types, such as skill bundles.",
    )

    def validate(self, attrs):
        attrs = validate_task_run_artifact_metadata(attrs)
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
    metadata = TaskRunArtifactMetadataSerializer(
        required=False,
        help_text="Optional structured metadata for special artifact types, such as skill bundles.",
    )
    storage_path = serializers.CharField(help_text="S3 object key reserved for the staged artifact")
    expires_in = serializers.IntegerField(help_text="Presigned POST expiry in seconds")
    presigned_post = S3PresignedPostSerializer(help_text="Presigned S3 POST configuration for uploading the file")

    def to_representation(self, instance: Any) -> dict[str, Any]:
        data = super().to_representation(instance)
        if data.get("metadata") is None:
            data.pop("metadata", None)
        return data


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
    metadata = TaskRunArtifactMetadataSerializer(
        required=False,
        help_text="Optional structured metadata for special artifact types, such as skill bundles.",
    )

    def validate(self, attrs):
        return validate_task_run_artifact_metadata(attrs)


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


TASK_SUMMARIES_MAX_IDS = 5000


class TaskSummariesRequestSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        max_length=TASK_SUMMARIES_MAX_IDS,
        help_text=(
            f"Task IDs to fetch summaries for (max {TASK_SUMMARIES_MAX_IDS}). Response is paginated; "
            f"follow the `next` cursor to retrieve all results."
        ),
    )


class TaskRunSummarySerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=tasks_facade.TaskRunStatus.choices, allow_null=True)
    environment = serializers.ChoiceField(choices=tasks_facade.TaskRunEnvironment.choices, allow_null=True)


class TaskSummarySerializer(DataclassSerializer):
    """Summary response for a task — reads from a frozen ``TaskSummaryDTO``."""

    latest_run = TaskRunSummarySerializer(allow_null=True, required=False)

    class Meta:
        dataclass = TaskSummaryDTO
        fields = ["id", "title", "repository", "created_at", "updated_at", "origin_product", "latest_run"]


class TaskListQuerySerializer(serializers.Serializer):
    """Query parameters for listing tasks"""

    origin_product = serializers.CharField(required=False, help_text="Filter by origin product")
    stage = serializers.CharField(required=False, help_text="Filter by task run stage")
    organization = serializers.CharField(required=False, help_text="Filter by repository organization")
    repository = serializers.CharField(
        required=False, help_text="Filter by repository name (can include org/repo format)"
    )
    created_by = serializers.IntegerField(required=False, help_text="Filter by creator user ID")
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Case-insensitive substring search over task title and description. A numeric value also matches the task number. An empty value disables the filter.",
    )
    status = serializers.ChoiceField(
        required=False,
        choices=[choice.value for choice in tasks_facade.TaskRunStatus],
        help_text="Filter tasks by the status of their most recent run.",
    )
    internal = serializers.ChoiceField(
        required=False,
        choices=["true", "false", "all"],
        help_text=(
            "Filter by the internal flag, which controls whether a task is shown by default, not whether "
            "it is accessible. Defaults to excluding internal tasks. Use 'all' to include both internal "
            "and user-facing tasks, or 'true' to list only internal tasks. All values are available to any "
            "team member; access stays governed by task visibility."
        ),
    )
    archived = serializers.ChoiceField(
        required=False,
        choices=["true", "false", "all"],
        help_text=(
            "Filter by archived state. Defaults to excluding archived tasks. Use 'true' to list only "
            "archived tasks, 'false' for the default, or 'all' to include both."
        ),
    )
    channel = serializers.UUIDField(required=False, help_text="Filter tasks to a channel's feed.")


class ChannelSerializer(DataclassSerializer):
    """Response shape for a task channel, read from a frozen ``ChannelDTO``."""

    created_by = TaskUserBasicInfoSerializer(allow_null=True, required=False)

    class Meta:
        dataclass = ChannelDTO
        fields = ["id", "name", "channel_type", "created_at", "created_by"]


class ChannelWriteSerializer(serializers.Serializer):
    """Request body for creating (resolve-or-create) or renaming a public channel."""

    name = serializers.CharField(
        max_length=128, help_text="Channel name, rendered as #<name>. Normalized to lowercase-dashed."
    )


class TaskThreadMessageSerializer(DataclassSerializer):
    """Response shape for one message in a task's thread."""

    author = TaskUserBasicInfoSerializer(allow_null=True, required=False)
    forwarded_by = TaskUserBasicInfoSerializer(allow_null=True, required=False)

    class Meta:
        dataclass = TaskThreadMessageDTO
        fields = ["id", "task", "content", "created_at", "author", "forwarded_to_agent_at", "forwarded_by"]


class TaskThreadMessageWriteSerializer(serializers.Serializer):
    """Request body for posting a thread message."""

    content = serializers.CharField(help_text="Message text.")


class TaskMentionQuerySerializer(serializers.Serializer):
    """Query parameters for listing mentions."""

    since = serializers.DateTimeField(
        required=False, help_text="Only return mentions created after this ISO 8601 timestamp."
    )
    limit = serializers.IntegerField(
        required=False,
        default=100,
        min_value=1,
        max_value=500,
        help_text="Maximum number of mentions to return (newest first).",
    )


class TaskMentionSerializer(DataclassSerializer):
    """Response shape for one @-mention of the requester in a task's thread."""

    author = TaskUserBasicInfoSerializer(allow_null=True, required=False)

    class Meta:
        dataclass = TaskMentionDTO
        fields = [
            "id",
            "message_id",
            "task_id",
            "task_title",
            "channel_id",
            "channel_name",
            "author",
            "content",
            "created_at",
        ]


class TaskRepositoriesResponseSerializer(serializers.Serializer):
    repositories = serializers.ListField(
        child=serializers.CharField(),
        help_text="Distinct repositories in use by non-deleted, non-internal tasks for the current team.",
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


class StreamReadTokenResponseSerializer(serializers.Serializer):
    """Response containing a JWT token (and resolved base URL) for reading a task run's live event stream"""

    token = serializers.CharField(
        help_text="Run-scoped JWT the browser presents to the agent-proxy to read this run's live event stream"
    )
    stream_base_url = serializers.CharField(
        allow_null=True,
        help_text=(
            "Base URL of the agent-proxy to read the stream from when routing via the proxy is enabled for "
            "this user. Null means read from the Django endpoint directly (same-origin). The client appends "
            "the run's stream path and sends the token as a Bearer header when this is set."
        ),
    )


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
    custom_image_id = serializers.UUIDField(
        required=False,
        default=None,
        help_text="Optional custom base image for this cloud run's sandbox (Modal VM runtime only); "
        "takes precedence over the environment's image.",
    )
    pr_authorship_mode = serializers.ChoiceField(
        choices=PR_AUTHORSHIP_MODE_CHOICES,
        required=False,
        default=None,
        help_text="Whether pull requests for this run should be authored by the user or the bot.",
    )
    auto_publish = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "When true, the cloud run agent pushes its work and opens a draft pull request on "
            "completion without waiting for an explicit ask."
        ),
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
        help_text=(
            "Optional GitHub user token from PostHog Code for user-authored cloud pull requests. "
            "Prefer linking GitHub from Settings → Linked accounts so the server can manage tokens; "
            "this field remains supported for callers that still manage their own tokens."
        ),
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
    rtk_enabled = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "Whether rtk command-output compression is enabled for this run. Omitted or null "
            "follows the server-side default (enabled); false opts this run out."
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
            _capture_rejected_reasoning_effort(
                self.context,
                runtime_adapter=attrs.get("runtime_adapter"),
                model=attrs.get("model"),
                reasoning_effort=attrs.get("reasoning_effort"),
                error=reasoning_effort_error,
            )

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
        choices=[environment.value for environment in tasks_facade.TaskRunEnvironment],
        required=False,
        default=tasks_facade.TaskRunEnvironment.LOCAL,
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
    custom_image_id = serializers.UUIDField(
        required=False,
        default=None,
        help_text="Optional custom base image for this cloud run's sandbox (Modal VM runtime only); "
        "takes precedence over the environment's image.",
    )
    pr_authorship_mode = serializers.ChoiceField(
        choices=PR_AUTHORSHIP_MODE_CHOICES,
        required=False,
        default=None,
        help_text="Whether pull requests for this run should be authored by the user or the bot.",
    )
    auto_publish = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "When true, the cloud run agent pushes its work and opens a draft pull request on "
            "completion without waiting for an explicit ask."
        ),
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
    rtk_enabled = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "Whether rtk command-output compression is enabled for this run. Omitted or null "
            "follows the server-side default (enabled); false opts this run out."
        ),
    )
    home_quick_action = serializers.CharField(
        required=False,
        default=None,
        allow_blank=False,
        max_length=120,
        help_text="Label of the Home-tab quick action that started this run (e.g. 'Fix CI'), surfaced on the workstream.",
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
            _capture_rejected_reasoning_effort(
                self.context,
                runtime_adapter=attrs.get("runtime_adapter"),
                model=attrs.get("model"),
                reasoning_effort=attrs.get("reasoning_effort"),
                error=reasoning_effort_error,
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class WarmTaskRequestSerializer(serializers.Serializer):
    """Request body for warming a full idling Run while composing a Code-app cloud task.

    Collection-level: no task exists yet at typing time. The warmer births a draft Task and an
    interactive Run that boots, clones, checks out `branch`, and starts the agent, then idles awaiting
    the first message. `github_integration` is a plain integration PK (an integer); the view re-scopes
    it to the caller's team before use.
    """

    repository = serializers.CharField(
        max_length=255,
        help_text="Target GitHub repository to clone, in `organization/repo` format (e.g. `posthog/posthog`).",
    )
    github_integration = serializers.IntegerField(
        help_text="Primary key of the team's GitHub integration to clone with.",
    )
    branch = serializers.CharField(
        required=False,
        default=None,
        allow_blank=True,
        allow_null=True,
        max_length=255,
        help_text="Branch to check out in the warm sandbox. Defaults to the repository's default branch when omitted.",
    )
    runtime_adapter = serializers.ChoiceField(
        choices=[adapter.value for adapter in RuntimeAdapter],
        required=False,
        default=None,
        allow_null=True,
        help_text=(
            "Agent runtime adapter to warm the sandbox on ('claude' or 'codex'). The warm Run starts the "
            "agent on this runtime so a matching submit reuses it; a submit selecting a different runtime "
            "falls through to a cold Run instead of reusing a mismatched warm session."
        ),
    )
    model = serializers.CharField(
        required=False,
        default=None,
        allow_blank=False,
        allow_null=True,
        help_text="LLM model identifier to warm the sandbox on. A submit selecting a different model won't reuse this warm Run.",
    )
    reasoning_effort = serializers.ChoiceField(
        choices=[effort.value for effort in PUBLIC_REASONING_EFFORTS],
        required=False,
        default=None,
        allow_null=True,
        help_text="Reasoning effort to warm the sandbox on for models that expose an effort control.",
    )

    def validate_repository(self, value: str) -> str:
        normalized = value.strip().lower()
        parts = normalized.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise serializers.ValidationError("Repository must be in the format organization/repository")
        return normalized


class WarmTaskResponseSerializer(serializers.Serializer):
    """Response for a successful warm request — the draft Task + idling warm Run reused on submit."""

    task_id = serializers.UUIDField(
        help_text="Id of the draft Task birthed for the warm Run.",
    )
    run_id = serializers.UUIDField(
        help_text="Id of the idling warm Run. The normal create+run path reuses and activates it on submit.",
    )


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
    custom_image_id = serializers.UUIDField(
        required=False,
        default=None,
        help_text="Optional custom base image for this cloud run's sandbox (Modal VM runtime only); "
        "takes precedence over the environment's image.",
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
        help_text=(
            "Optional GitHub user token from PostHog Code for user-authored cloud pull requests. "
            "Prefer linking GitHub from Settings → Linked accounts so the server can manage tokens; "
            "this field remains supported for callers that still manage their own tokens."
        ),
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


class TaskAutomationSerializer(DataclassSerializer):
    """Detail/create/update/run response for a task automation."""

    class Meta:
        dataclass = TaskAutomationDTO
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


class TaskAutomationWriteSerializer(serializers.Serializer):
    """Request body for creating or updating a task automation."""

    name = serializers.CharField(max_length=255, help_text="Display name (stored as the backing task's title).")
    prompt = serializers.CharField(help_text="The automation prompt (stored as the backing task's description).")
    repository = serializers.CharField(
        max_length=255, help_text="Target repository in the format organization/repository."
    )
    github_integration = TeamScopedPrimaryKeyRelatedField(
        queryset=Integration.objects.filter(kind="github"),
        required=False,
        allow_null=True,
        help_text="GitHub integration to run as. Defaults to the team's GitHub integration when omitted.",
    )
    cron_expression = serializers.CharField(
        max_length=100, help_text="Standard 5-field cron expression (minute hour day month weekday)."
    )
    timezone = serializers.CharField(
        max_length=128, required=False, default="UTC", help_text="IANA timezone the schedule runs in."
    )
    template_id = serializers.CharField(
        max_length=255,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional template identifier this automation was created from.",
    )
    enabled = serializers.BooleanField(
        required=False, default=True, help_text="Whether the schedule is active; paused when false."
    )

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


class SandboxEnvironmentSerializer(DataclassSerializer):
    """Detail/create/update response for a sandbox environment."""

    created_by = TaskUserBasicInfoSerializer(allow_null=True, required=False)

    class Meta:
        dataclass = SandboxEnvironmentDTO
        fields = [
            "id",
            "name",
            "network_access_level",
            "allowed_domains",
            "include_default_domains",
            "repositories",
            "has_environment_variables",
            "private",
            "internal",
            "effective_domains",
            "created_by",
            "created_at",
            "updated_at",
            "custom_image_id",
            "custom_image_name",
            "custom_image_status",
        ]


class SandboxEnvironmentListSerializer(DataclassSerializer):
    """List response for sandbox environments (subset of fields)."""

    created_by = TaskUserBasicInfoSerializer(allow_null=True, required=False)

    class Meta:
        dataclass = SandboxEnvironmentDTO
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
            "custom_image_id",
            "custom_image_name",
            "custom_image_status",
        ]


class SandboxEnvironmentWriteSerializer(serializers.Serializer):
    """Request body for creating or updating a sandbox environment."""

    name = serializers.CharField(max_length=255, help_text="Display name for the environment.")
    network_access_level = serializers.ChoiceField(
        choices=tasks_facade.SandboxNetworkAccessLevel.choices,
        required=False,
        default=tasks_facade.SandboxNetworkAccessLevel.FULL,
        help_text="Network access policy: trusted (default allowlist), full (unrestricted), or custom.",
    )
    allowed_domains = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        default=list,
        help_text="Allowed domains for custom network access.",
    )
    include_default_domains = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether to include default trusted domains (GitHub, npm, PyPI).",
    )
    repositories = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        default=list,
        help_text="Repositories this environment applies to (format: org/repo).",
    )
    environment_variables = serializers.JSONField(
        write_only=True,
        required=False,
        default=dict,
        help_text="Encrypted environment variables (write-only, never returned in responses).",
    )
    private = serializers.BooleanField(
        required=False,
        default=True,
        help_text="If true, only the creator can see this environment; otherwise the whole team can.",
    )
    custom_image_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Custom base image for this environment's sandboxes (Modal VM runtime only); null uses the default base.",
    )

    def validate_environment_variables(self, value):
        if value:
            for key in value:
                if not tasks_facade.is_valid_sandbox_env_var_key(key):
                    raise serializers.ValidationError(
                        f"Invalid environment variable key: {key!r}. Must match [A-Za-z_][A-Za-z0-9_]*"
                    )
                if tasks_facade.is_blocked_sandbox_env_var_key(key):
                    raise serializers.ValidationError(
                        f"Environment variable key {key!r} is not allowed: it can change how sandbox "
                        "processes execute code (e.g. NODE_OPTIONS, LD_PRELOAD)."
                    )
                if tasks_facade.is_reserved_sandbox_env_var_key(key):
                    raise serializers.ValidationError(
                        f"Environment variable key {key!r} is reserved and managed by PostHog; it cannot be set."
                    )
        return value


class SandboxCustomImageSerializer(DataclassSerializer):
    """Detail response for a custom sandbox base image."""

    created_by = TaskUserBasicInfoSerializer(allow_null=True, required=False)

    class Meta:
        dataclass = SandboxCustomImageDTO
        fields = [
            "id",
            "name",
            "description",
            "repository",
            "private",
            "status",
            "version",
            "modal_image_name",
            "spec",
            "spec_yaml",
            "scan_result",
            "build_log",
            "error",
            "builder_task_id",
            "created_by",
            "created_at",
            "updated_at",
        ]


class SandboxCustomImageWriteSerializer(serializers.Serializer):
    """Request body for creating a custom sandbox base image."""

    name = serializers.CharField(max_length=255, help_text="Display name for the custom image.")
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="What should go into the image; seeds the image-builder agent conversation.",
    )
    repository = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        max_length=255,
        help_text="Optional 'org/repo' the builder session clones so it can verify the image "
        "brings up that repository's dependencies.",
    )
    private = serializers.BooleanField(
        required=False,
        default=False,
        help_text="If true, only you can see and use this image; otherwise the whole team can.",
    )


class SandboxCustomImageBuildSerializer(serializers.Serializer):
    """Request body for scanning and building a custom sandbox base image."""

    spec_yaml = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Image spec YAML to build. When omitted, the spec is read from the builder agent's live sandbox.",
    )


class TaskPresenceBeaconRequestSerializer(serializers.Serializer):
    """Request body for the presence beacon and beacon-leave endpoints.

    `device_id` is the UUID of the caller's `UserPushToken` row, which the
    client received when it registered for push via `/api/users/@me/push_tokens/`.
    The client is expected to use the same identifier on the beacon and leave
    calls; if the user has unregistered the underlying push token, the value
    won't resolve and the call returns 404 — at which point pushes were
    already not going there anyway.
    """

    device_id = serializers.UUIDField(
        help_text="UUID of the caller's UserPushToken (returned by `/api/users/@me/push_tokens/` on register).",
    )


class SlackThreadContextQuerySerializer(serializers.Serializer):
    """Query params for the slack-thread debug endpoint."""

    url = serializers.URLField(
        help_text=(
            "Full Slack permalink to any message in the thread (e.g. "
            "https://posthog.slack.com/archives/C…/p1779956938619299). Replies inside the "
            "thread are accepted too — the `thread_ts` query param (when present) takes "
            "precedence over the in-path message ts."
        ),
    )


class SlackThreadContextThreadSerializer(serializers.Serializer):
    """Slack-side identifiers and the mapping metadata for a thread → task lookup."""

    url = serializers.CharField(help_text="Echoed input URL.")
    channel = serializers.CharField(help_text="Slack channel id parsed from the URL (e.g. C0ACRAMJUAG).")
    thread_ts = serializers.CharField(help_text="Slack thread_ts (e.g. 1779956938.619299).")
    slack_workspace_id = serializers.CharField(
        allow_null=True,
        help_text="Slack workspace id (e.g. T…). Null when no mapping exists yet.",
    )
    mentioning_slack_user_id = serializers.CharField(
        allow_null=True,
        help_text="The Slack user who triggered the task. Null when no mapping exists yet.",
    )


class SlackThreadContextTaskSerializer(serializers.Serializer):
    """The PostHog Task linked to the Slack thread."""

    id = serializers.CharField(help_text="UUID of the Task row.")
    team_id = serializers.IntegerField(help_text="Team that owns the task.")
    title = serializers.CharField(help_text="Task title (typically the first ~255 chars of the Slack ask).")
    repository = serializers.CharField(
        allow_null=True,
        help_text="Resolved repository in `org/repo` form, or null if the run started without a repo.",
    )
    origin_product = serializers.CharField(help_text="`Task.OriginProduct` (`slack` for slack-originated tasks).")
    created_at = serializers.DateTimeField(help_text="When the task was created (server-side timestamp).")
    url = serializers.CharField(help_text="Absolute URL to the task detail page in the PostHog app.")


class SlackThreadContextRepoResearchSerializer(serializers.Serializer):
    """The internal sandbox run the discovery agent used to pick this run's repo.

    Only present when the originating mention was ambiguous (multiple candidate
    repos, no explicit mention) — that's the only path that spins up a research
    sandbox. Null otherwise.
    """

    task_id = serializers.CharField(help_text="UUID of the internal repo-research Task.")
    run_id = serializers.CharField(help_text="UUID of the internal repo-research TaskRun.")
    status = serializers.CharField(
        allow_null=True,
        help_text="Research run status, or null if the run row could not be loaded.",
    )
    task_processing_workflow_id = serializers.CharField(
        help_text="Temporal workflow id for the research sandbox run (`task-processing-<task_id>-<run_id>`).",
    )
    task_processing_workflow_url = serializers.CharField(
        allow_null=True,
        help_text="Full Temporal Web UI URL for the research workflow; null when `TEMPORAL_UI_HOST` is unset.",
    )
    sandbox_url = serializers.CharField(
        allow_null=True,
        help_text="Live sandbox tunnel URL for the research run, when one was attached.",
    )
    task_view_url = serializers.CharField(
        help_text="Absolute URL to the research task detail page (carries `?ph_debug=true`).",
    )
    log_url = serializers.CharField(
        allow_null=True,
        help_text="Presigned S3 URL for the research run's JSONL log transcript (valid ~1 hour).",
    )


class SlackThreadContextRunSerializer(serializers.Serializer):
    """One TaskRun and its associated Temporal workflow handles."""

    id = serializers.CharField(help_text="UUID of the TaskRun row.")
    status = serializers.CharField(help_text="Run status (queued/in_progress/completed/failed/…).")
    created_at = serializers.DateTimeField(help_text="When the run was created.")
    completed_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When the run reached a terminal state, or null while still running.",
    )
    sandbox_url = serializers.CharField(
        allow_null=True,
        help_text="Live sandbox tunnel URL, when one was attached.",
    )
    pr_url = serializers.CharField(
        allow_null=True,
        help_text="PR URL produced by the run, when one was opened.",
    )
    error_message = serializers.CharField(
        allow_null=True,
        help_text="Error captured on terminal failure, or null on success.",
    )
    task_processing_workflow_id = serializers.CharField(
        help_text="Temporal workflow id for the sandbox/agent run (`task-processing-<task_id>-<run_id>`).",
    )
    task_processing_workflow_url = serializers.CharField(
        allow_null=True,
        help_text="Full Temporal Web UI URL for the task-processing workflow; null when `TEMPORAL_UI_HOST` is unset.",
    )
    mention_workflow_id = serializers.CharField(
        allow_null=True,
        help_text=(
            "Temporal workflow id of the Slack mention that dispatched this run "
            "(`posthog-code-mention-<workspace>:<event_id_or_channel:ts>`). Null for runs "
            "created before this field was persisted."
        ),
    )
    mention_workflow_url = serializers.CharField(
        allow_null=True,
        help_text="Full Temporal Web UI URL for the mention dispatch workflow; null when unavailable.",
    )
    task_view_url = serializers.CharField(help_text="Absolute URL to the task detail page focused on this run.")
    log_url = serializers.CharField(
        allow_null=True,
        help_text="Presigned S3 URL for the run's full JSONL log transcript (valid ~1 hour).",
    )
    repo_research = SlackThreadContextRepoResearchSerializer(
        allow_null=True,
        help_text="The discovery-agent sandbox that picked this run's repo, when the mention was ambiguous.",
    )


class SlackThreadContextResponseSerializer(serializers.Serializer):
    """Top-level response for the slack-thread debug endpoint."""

    thread = SlackThreadContextThreadSerializer(help_text="Slack-side identifiers and the mapping metadata.")
    task = SlackThreadContextTaskSerializer(
        allow_null=True,
        help_text="Linked PostHog Task. Null when no mapping was found for the thread.",
    )
    runs = SlackThreadContextRunSerializer(
        many=True,
        help_text="All runs on the task, oldest first. Empty when no mapping was found.",
    )


class AgentProxyCallbackRequestSerializer(serializers.Serializer):
    """Request body for the agent-proxy side-effect callback.

    Called by the standalone Node agent-proxy after it accepts an ingest event
    that triggers a Temporal heartbeat or an awaiting-input push notification.
    The request is authenticated with the original sandbox event ingest JWT so
    Django can re-validate claims without an extra token round-trip.
    """

    kind = serializers.ChoiceField(
        choices=["heartbeat", "awaiting_input"],
        help_text=(
            "Side effect to dispatch. 'heartbeat' signals the Temporal workflow to reset its "
            "inactivity timer. 'awaiting_input' fires a mobile push notification when an "
            "interactive run finishes a turn and is waiting for user input."
        ),
    )
    agent_active = serializers.BooleanField(
        help_text=(
            "Whether the agent is currently active (true) or idle (false). "
            "For 'heartbeat' callbacks this is always true. "
            "For 'awaiting_input' callbacks this is always false."
        ),
    )
    task_id = serializers.CharField(
        max_length=36,
        help_text="UUID of the Task that owns this run. Must match the JWT claim.",
    )
    team_id = serializers.IntegerField(
        min_value=1,
        help_text="Numeric team (project) ID. Must match the JWT claim.",
    )


class AgentProxyCallbackResponseSerializer(serializers.Serializer):
    """Response from the agent-proxy side-effect callback."""

    dispatched = serializers.BooleanField(
        help_text="True when the requested side effect was dispatched; false when skipped (e.g. run not found)."
    )
