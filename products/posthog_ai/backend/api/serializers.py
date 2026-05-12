from typing import Any
from uuid import UUID

from django.utils import timezone

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from posthog.api.shared import UserBasicSerializer

from products.posthog_ai.backend.models import MAX_WATCHED_QUESTIONS_PER_TEAM, TrackedQuestion, TrackedQuestionRun
from products.posthog_ai.backend.services.scheduling import compute_next_run_at


class TrackedQuestionRunSerializer(serializers.ModelSerializer):
    """Single run of a TrackedQuestion — used for sparkline-style history rendering."""

    id = serializers.UUIDField(read_only=True, help_text="UUID of the run record.")
    state = serializers.ChoiceField(
        choices=TrackedQuestionRun.State.choices,
        read_only=True,
        help_text="ok / drifted / error / skipped — the lifecycle outcome of this run.",
    )
    severity = serializers.ChoiceField(
        choices=TrackedQuestionRun.Severity.choices,
        read_only=True,
        help_text="Judge-assigned drift severity: none / minor / moderate / significant.",
    )
    judge_summary = serializers.CharField(
        read_only=True,
        help_text="One-to-two sentence summary of what the drift judge concluded.",
    )
    narrative = serializers.CharField(
        read_only=True,
        help_text="Max's full natural-language comparison of the current data against the baseline.",
    )
    forked_conversation_id = serializers.UUIDField(
        read_only=True,
        source="forked_conversation_id",
        allow_null=True,
        help_text="UUID of the Conversation Max produced when comparing against the baseline.",
    )
    signal_emitted_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When (if ever) an emit_signal() call was made for this run. Null when the run was non-drift.",
    )
    error = serializers.CharField(
        read_only=True,
        help_text="Error message if state=error. Empty otherwise.",
    )
    created_at = serializers.DateTimeField(
        read_only=True,
        help_text="When this run was executed.",
    )

    class Meta:
        model = TrackedQuestionRun
        fields = [
            "id",
            "state",
            "severity",
            "judge_summary",
            "narrative",
            "forked_conversation_id",
            "signal_emitted_at",
            "error",
            "created_at",
        ]
        read_only_fields = fields


class TrackedQuestionSerializer(serializers.ModelSerializer):
    """A Max AI answer the user has chosen to watch on a cadence."""

    id = serializers.UUIDField(read_only=True, help_text="UUID of the watched question.")
    created_by = UserBasicSerializer(read_only=True, help_text="The user who started watching this answer.")
    conversation_id = serializers.UUIDField(
        source="source_conversation_id",
        help_text="UUID of the Max conversation the watched answer was generated in.",
    )
    human_message_id = serializers.UUIDField(
        source="source_human_message_id",
        help_text="UUID of the user-authored HumanMessage that asked the question.",
    )
    visualization_message_id = serializers.UUIDField(
        source="source_visualization_message_id",
        help_text="UUID of the AI VisualizationMessage that contains the query being watched.",
    )
    title = serializers.CharField(
        max_length=255,
        help_text="Short label shown in the watched-questions panel; defaults to the visualization title.",
    )
    question_text = serializers.CharField(
        read_only=True,
        help_text="Frozen snapshot of the user's original natural-language question.",
    )
    baseline_summary = serializers.CharField(
        read_only=True,
        help_text=(
            "AI-generated one-paragraph summary of the baseline answer; reused as the comparison anchor on each "
            "scheduled run."
        ),
    )
    baseline_captured_at = serializers.DateTimeField(
        read_only=True,
        help_text="When the baseline answer was captured (i.e. when the user first started watching).",
    )
    cadence = serializers.ChoiceField(
        choices=TrackedQuestion.Cadence.choices,
        help_text="How often the watched answer is re-evaluated against current data.",
    )
    status = serializers.ChoiceField(
        choices=TrackedQuestion.Status.choices,
        read_only=True,
        help_text="active / paused / archived. Only active questions are evaluated by the scheduler.",
    )
    next_run_at = serializers.DateTimeField(
        read_only=True,
        help_text="UTC timestamp of the next scheduled drift-check run.",
    )
    last_run_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="UTC timestamp of the most recent completed drift-check run.",
    )
    repository = serializers.CharField(
        allow_blank=True,
        required=False,
        max_length=255,
        help_text=(
            "Optional 'owner/repo' identifier. When a drift signal is emitted, downstream Signals → Tasks → PR "
            "pipeline will target this repository. Leave blank to omit the repo pin."
        ),
    )
    recent_runs = serializers.SerializerMethodField(
        help_text="Up to 6 most-recent TrackedQuestionRun entries, newest first, for sparkline-style rendering.",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the watch was created.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the watch was last edited.")

    class Meta:
        model = TrackedQuestion
        fields = [
            "id",
            "created_by",
            "conversation_id",
            "human_message_id",
            "visualization_message_id",
            "title",
            "question_text",
            "baseline_summary",
            "baseline_captured_at",
            "cadence",
            "status",
            "next_run_at",
            "last_run_at",
            "repository",
            "recent_runs",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "question_text",
            "baseline_summary",
            "baseline_captured_at",
            "status",
            "next_run_at",
            "last_run_at",
            "recent_runs",
            "created_at",
            "updated_at",
        ]

    def get_recent_runs(self, obj: TrackedQuestion) -> Any:
        runs = obj.runs.order_by("-created_at")[:6]
        return TrackedQuestionRunSerializer(runs, many=True).data

    def validate_conversation_id(self, value: UUID) -> UUID:
        from ee.models.assistant import Conversation

        team = self.context["get_team"]()
        if not Conversation.objects.filter(id=value, team=team).exists():
            raise ValidationError("Conversation not found for this team.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if self.instance is None:
            team = self.context["get_team"]()
            active_count = TrackedQuestion.objects.filter(team=team, status=TrackedQuestion.Status.ACTIVE).count()
            if active_count >= MAX_WATCHED_QUESTIONS_PER_TEAM:
                raise ValidationError(
                    f"Team has reached the limit of {MAX_WATCHED_QUESTIONS_PER_TEAM} active watched questions. "
                    "Archive an existing watch before creating a new one."
                )
        return attrs

    def create(self, validated_data: dict[str, Any]) -> TrackedQuestion:
        from products.posthog_ai.backend.services.baseline_summary import generate_baseline_summary_for_message
        from products.posthog_ai.backend.services.conversation_fork import load_conversation_message_pair
        from products.signals.backend.models import SignalSourceConfig

        request = self.context.get("request")
        team = self.context["get_team"]()
        user = request.user if request is not None else None

        conversation_id = validated_data.pop("source_conversation_id")
        human_message_id = validated_data.pop("source_human_message_id")
        visualization_message_id = validated_data.pop("source_visualization_message_id")
        cadence = validated_data.get("cadence", TrackedQuestion.Cadence.WEEKLY)

        # Resolve the baseline messages and synthesize a one-paragraph anchor summary.
        message_pair = load_conversation_message_pair(
            conversation_id=conversation_id,
            human_message_id=human_message_id,
            visualization_message_id=visualization_message_id,
            team=team,
        )
        baseline_summary = generate_baseline_summary_for_message(
            question_text=message_pair.question_text,
            visualization_message=message_pair.visualization_message_dict,
        )

        now = timezone.now()
        tracked_question = TrackedQuestion.objects.create(
            team=team,
            created_by=user if user and user.is_authenticated else None,
            source_conversation_id=conversation_id,
            source_human_message_id=human_message_id,
            source_visualization_message_id=visualization_message_id,
            title=validated_data.get("title") or message_pair.visualization_title,
            question_text=message_pair.question_text,
            baseline_summary=baseline_summary,
            baseline_captured_at=now,
            cadence=cadence,
            status=TrackedQuestion.Status.ACTIVE,
            next_run_at=compute_next_run_at(cadence=cadence, anchor=now, team=team),
            repository=validated_data.get("repository", ""),
        )

        # The user's "Watch this answer" click is the consent gesture that enables the signal source
        # for the entire team. This is idempotent — re-clicking just refreshes the row.
        SignalSourceConfig.objects.update_or_create(
            team=team,
            source_product=SignalSourceConfig.SourceProduct.POSTHOG_AI,
            source_type=SignalSourceConfig.SourceType.QUESTION_DRIFT,
            defaults={
                "enabled": True,
                "created_by": user if user and user.is_authenticated else None,
            },
        )
        return tracked_question

    def update(self, instance: TrackedQuestion, validated_data: dict[str, Any]) -> TrackedQuestion:
        cadence = validated_data.get("cadence", instance.cadence)
        if cadence != instance.cadence:
            instance.cadence = cadence
            instance.next_run_at = compute_next_run_at(cadence=cadence, anchor=timezone.now(), team=instance.team)
        if "title" in validated_data:
            instance.title = validated_data["title"]
        if "repository" in validated_data:
            instance.repository = validated_data["repository"]
        instance.save()
        return instance
