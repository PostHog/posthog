"""DRF serializers for wizard. Bound to facade DTOs, not Django models."""

from typing import Any

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from products.wizard.backend.facade.contracts import (
    RepositoryDetectionDTO,
    UpsertRepositoryDetectionRequest,
    UpsertWizardSessionRequest,
    WizardSessionDTO,
)

# Bounds on the pending question. A prompt is a terminal question, not a document, and the wizard
# asks one thing at a time; the caps keep a malformed or hostile push from growing the row that the
# app-wide widget reads on every page load.
MAX_PROMPT_LENGTH = 2000
MAX_PROMPTS = 10

# Bound on the handoff doc. It IS a document (the wizard's setup report, a few KB of markdown in
# practice), but the row is streamed over SSE and republished on every later upsert, so cap it well
# below anything a hostile push could use to balloon the channel. The CLI truncates to the same cap.
MAX_HANDOFF_TEXT_LENGTH = 64 * 1024


class PendingInputSerializer(serializers.Serializer):
    """The in-flight `wizard_ask` question. Typed rather than a free-form dict so the shape the
    widget renders is enforced at the edge instead of trusted from the producer."""

    id = serializers.CharField(
        max_length=255,
        help_text="Identifier the wizard mints for this question. Changes when a new question is asked.",
    )
    asked_at = serializers.DateTimeField(
        required=False,
        help_text="UTC timestamp when the wizard asked. Defaults to the session's update time when absent.",
    )
    question_count = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        help_text="How many questions this single ask covers.",
    )
    sensitive = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether the answer is a secret. Sensitive questions never carry prompt text.",
    )
    prompts = serializers.ListField(
        required=False,
        max_length=MAX_PROMPTS,
        child=serializers.CharField(max_length=MAX_PROMPT_LENGTH, allow_blank=True),
        help_text="The question text shown to the user. Always empty for sensitive questions.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # Redact here rather than in the client: the sensitive contract has to hold for every
        # producer, and past this point the value is persisted, streamed over SSE, and logged.
        if attrs.get("sensitive"):
            attrs.pop("prompts", None)
        asked_at = attrs.get("asked_at")
        if asked_at is not None:
            # The field is a JSONField on the model, which can't hold a datetime.
            attrs["asked_at"] = asked_at.isoformat()
        return attrs


class WizardSessionSerializer(DataclassSerializer):
    """Output: serialises a WizardSessionDTO returned by the facade."""

    pending_input = PendingInputSerializer(
        allow_null=True,
        help_text="The question the wizard is currently blocked on, or null when nothing is pending.",
    )

    class Meta:
        dataclass = WizardSessionDTO
        extra_kwargs = {
            "created_by": {
                "help_text": (
                    "The user who initiated this wizard run (null for runs created before "
                    "attribution existed). Lets the UI name whose run it is."
                ),
            },
            "handoff_text": {
                "help_text": (
                    "Markdown handoff doc the wizard produced for this run (its setup report), "
                    "or null while the run hasn't written one. Sticky once set."
                ),
            },
        }


# Bounds on a detection report. A detection is a shallow repo classification (one row per
# project manifest found), not a document — the caps keep a malformed or hostile push from
# growing a row the app reads when rendering setup recommendations.
MAX_DETECTED_PROJECTS = 200
MAX_DETECTION_ERROR_MESSAGE_LENGTH = 2000


class DetectedProjectSerializer(serializers.Serializer):
    """One project the detection agent found in the repository."""

    path = serializers.CharField(
        max_length=512,
        help_text="Repo-relative path of the project ('.' for the repository root).",
    )
    framework = serializers.CharField(
        max_length=100,
        help_text="Human-readable framework name the agent classified, e.g. 'Next.js'.",
    )
    variant = serializers.CharField(
        max_length=64,
        required=False,
        allow_null=True,
        help_text=(
            "Detection-kind-specific target the project matched (e.g. the source-map skill "
            "variant 'nextjs'), or null when the stack isn't supported."
        ),
    )
    has_posthog = serializers.BooleanField(
        help_text="Whether a PostHog SDK is already installed in this project.",
    )
    instrumentable = serializers.BooleanField(
        help_text="Whether the detection kind can act on this project (supported variant + SDK present).",
    )
    reason = serializers.CharField(
        max_length=300,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Why the project is not instrumentable, when it isn't. Human-readable.",
    )


class DetectionReportSerializer(serializers.Serializer):
    """The structured result of one detection run. Typed rather than a free-form dict so the
    shape the app renders is enforced at the edge instead of trusted from the producer."""

    repo_type = serializers.ChoiceField(
        choices=["monorepo", "single"],
        help_text="Whether the repository is a multi-project workspace or a single project.",
    )
    projects = DetectedProjectSerializer(
        many=True,
        # many_init forwards this to the ListSerializer; the stubs don't model that.
        max_length=MAX_DETECTED_PROJECTS,  # type: ignore[call-arg]
        help_text="Projects found in the repository, one entry per project manifest.",
    )


class DetectionErrorSerializer(serializers.Serializer):
    """Why a detection run failed. Populated instead of `report`."""

    type = serializers.CharField(
        max_length=100,
        required=False,
        allow_null=True,
        help_text="Machine-readable failure category, e.g. 'no-manifests', 'agent-error'.",
    )
    message = serializers.CharField(
        max_length=MAX_DETECTION_ERROR_MESSAGE_LENGTH,
        help_text="Human-readable failure description.",
    )


class RepositoryDetectionSerializer(DataclassSerializer):
    """Output: serialises a RepositoryDetectionDTO returned by the facade."""

    report = DetectionReportSerializer(
        allow_null=True,
        help_text="The detection result, or null when the run failed (see `error`).",
    )
    error = DetectionErrorSerializer(
        allow_null=True,
        help_text="Why the run failed, or null when it succeeded (see `report`).",
    )

    class Meta:
        dataclass = RepositoryDetectionDTO
        extra_kwargs = {
            "repository": {
                "help_text": "Repository the detection ran against, in 'org/repo' form.",
            },
            "kind": {
                "help_text": "Detection flavor, e.g. 'error-tracking-source-maps'.",
            },
            "task_run_id": {
                "help_text": "TaskRun UUID of the cloud run that produced this result, when it ran in the cloud.",
            },
        }


class UpsertRepositoryDetectionRequestSerializer(DataclassSerializer):
    """Input: validates the JSON a detection agent posts. team_id is derived from URL."""

    report = DetectionReportSerializer(
        required=False,
        allow_null=True,
        help_text="The detection result. Exactly one of `report` / `error` must be set.",
    )
    error = DetectionErrorSerializer(
        required=False,
        allow_null=True,
        help_text="Why the run failed. Exactly one of `report` / `error` must be set.",
    )
    task_run_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="TaskRun UUID of the cloud run producing this result. Omit for local runs.",
    )

    class Meta:
        dataclass = UpsertRepositoryDetectionRequest
        extra_kwargs = {
            "repository": {
                "max_length": 255,
                "help_text": (
                    "Repository the detection ran against, in 'org/repo' form. Together with "
                    "`kind` this is the idempotency anchor — reposting the same pair replaces "
                    "the existing row."
                ),
            },
            "kind": {
                "max_length": 64,
                "help_text": "Detection flavor, e.g. 'error-tracking-source-maps'.",
            },
        }

    def validate_task_run_id(self, value: Any) -> str | None:
        # The contract dataclass carries a plain string; UUIDField only validates format.
        return str(value) if value is not None else None

    def validate(self, attrs: UpsertRepositoryDetectionRequest) -> UpsertRepositoryDetectionRequest:
        # DataclassSerializer hands validate() the built dataclass, not a dict.
        if (attrs.report is not None) == (attrs.error is not None):
            raise serializers.ValidationError("Exactly one of `report` or `error` must be provided.")
        return attrs


class UpsertWizardSessionRequestSerializer(DataclassSerializer):
    """Input: validates the JSON the wizard CLI posts. team_id is derived from URL."""

    pending_input = PendingInputSerializer(
        required=False,
        allow_null=True,
        help_text=(
            "Populated while the wizard is blocked on a question in the terminal. "
            "Null/absent means no input is pending; a push without it clears the previous prompt."
        ),
    )
    # trim_whitespace would mangle markdown that opens with indentation (e.g. a code block).
    handoff_text = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
        max_length=MAX_HANDOFF_TEXT_LENGTH,
        help_text=(
            "Markdown handoff doc for the run (the wizard's setup report). Send it once the run "
            "has produced one; omitting it on later pushes keeps the stored value."
        ),
    )

    class Meta:
        dataclass = UpsertWizardSessionRequest
        extra_kwargs = {
            "session_id": {
                "max_length": 255,
                "help_text": (
                    "Stable identifier the wizard mints for this run "
                    "(format: '{workflow_id}-{skill_id}-{started_at_iso}'). "
                    "Reposting with the same session_id upserts the existing row."
                ),
            },
            "workflow_id": {
                "max_length": 255,
                "help_text": "High-level workflow being run, e.g. 'onboarding', 'migration', 'audit'.",
            },
            "skill_id": {
                "max_length": 255,
                "help_text": "Specific skill within the workflow, e.g. 'nextjs', 'django', 'laravel'.",
            },
            "started_at": {
                "help_text": "UTC timestamp when the wizard started this run. Matches the timestamp encoded in session_id.",
            },
            "run_phase": {
                "help_text": "Lifecycle stage of the wizard run.",
            },
            "event_plan": {
                "help_text": "Optional structured plan of events the wizard intends to instrument. Schema is workflow-specific.",
            },
            "error": {
                "help_text": "Populated when run_phase='error'. Shape: { type: string, message: string }.",
            },
        }
