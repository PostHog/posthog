"""DRF serializers for wizard."""

from rest_framework import serializers

from products.wizard.backend.models import WizardSession


class WizardTaskSerializer(serializers.Serializer):
    id = serializers.CharField(
        help_text="Stable identifier the wizard assigned to this task. Used to track lifecycle across pushes."
    )
    title = serializers.CharField(
        help_text="Human-readable title of the task. Should be updated if the task's purpose changes, but can remain the same if only the status changes."
    )
    status = serializers.ChoiceField(
        choices=["pending", "in_progress", "completed", "failed", "canceled"],
        help_text="Current lifecycle stage of the task.",
    )


class WizardSessionSerializer(serializers.ModelSerializer):
    session_id = serializers.CharField(
        help_text=(
            "Stable identifier the wizard assigns to a run, formatted "
            "'{workflow_id}-{skill_id}-{started_at_iso}'. Re-posting with the same "
            "session_id upserts the existing row."
        )
    )
    workflow_id = serializers.CharField(
        help_text="High-level workflow being run, e.g. 'onboarding', 'migration', 'audit'."
    )
    skill_id = serializers.CharField(
        help_text="Specific skill within the workflow, e.g. 'posthog_integration', 'revenue_analytics_setup'."
    )
    started_at = serializers.DateTimeField(
        help_text="UTC timestamp when the wizard started this run. Matches the timestamp encoded in session_id."
    )
    run_phase = serializers.ChoiceField(
        choices=["idle", "running", "completed", "error"],
        help_text="Lifecycle stage of the wizard run.",
    )
    tasks = WizardTaskSerializer(
        many=True,
        help_text=(
            "Full snapshot of the wizard's current task list. Each push overwrites the previous list; "
            "tasks may be added, removed, or re-ordered between pushes."
        ),
    )
    event_plan = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text="Optional structured plan of events the wizard intends to instrument. Schema is workflow-specific.",
    )
    error = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text="Populated when run_phase='error'. Shape: { type: string, message: string }.",
    )

    class Meta:
        model = WizardSession
        fields = [
            "session_id",
            "team_id",
            "workflow_id",
            "skill_id",
            "started_at",
            "run_phase",
            "tasks",
            "event_plan",
            "error",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["team_id", "created_at", "updated_at"]
