"""DRF serializers for wizard. Bound to facade DTOs, not Django models."""

from typing import Any

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from products.wizard.backend.facade.contracts import UpsertWizardSessionRequest, WizardSessionDTO

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
