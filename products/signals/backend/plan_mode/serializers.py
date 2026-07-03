from rest_framework import serializers

from products.signals.backend.models import SignalReport


class InboxPlanReportSerializer(serializers.ModelSerializer):
    """List representation of a plan report ("project").

    A plan report is an ordinary `SignalReport` surfaced in the Plan tab; this serializer exposes only
    the fields the list needs. Ordering (most-recent-first) is established upstream from the backing
    `inbox`/`plan` signal timestamps, not from these fields.
    """

    # Declared as a plain string rather than the model's `Status` ChoiceField on purpose: a bare
    # `status` enum collides with other `status` choice sets under drf-spectacular's `--fail-on-warn`
    # (see the improving-drf-endpoints skill). It's read-only here, so a string is all the list needs.
    status = serializers.CharField(
        read_only=True,
        help_text="Report lifecycle status (e.g. ready, resolved, suppressed).",
    )
    is_draft = serializers.SerializerMethodField(
        help_text="Whether the plan is still a draft (its planning conversation hasn't been finished)."
    )

    def get_is_draft(self, obj: SignalReport) -> bool:
        # The list view precomputes draft-ness in bulk (absence of a safety_judgment artefact — only
        # `finish_plan` writes one) and passes it via context.
        draft_ids: set[str] = self.context.get("draft_report_ids", set())
        return str(obj.id) in draft_ids

    class Meta:
        model = SignalReport
        fields = [
            "id",
            "title",
            "summary",
            "status",
            "is_draft",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "title": {"help_text": "The plan's title. Placeholder until the planning agent finalizes it."},
            "summary": {"help_text": "The plan's summary/description. Seeded from the user's initial description."},
            "created_at": {"help_text": "When the plan report was created."},
            "updated_at": {"help_text": "When the plan report was last updated."},
        }


class InboxPlanCreateSerializer(serializers.Serializer):
    """Body for creating a new plan: the user's brief initial description of the idea."""

    initial_description = serializers.CharField(
        max_length=4000,
        allow_blank=False,
        help_text="A brief initial description of the feature or change to plan. Seeds the plan's "
        "summary and the planning agent's first message.",
    )


class InboxPlanCreatedSerializer(serializers.Serializer):
    """Response for a created plan: the new report and its planning conversation."""

    report_id = serializers.CharField(help_text="The new plan report's id.")
    task_id = serializers.CharField(help_text="The planning conversation's task id.")
    run_id = serializers.CharField(
        allow_null=True, help_text="The planning conversation's initial run id, when already started."
    )


class InboxPlanFinishedSerializer(serializers.Serializer):
    """Response for a finished plan."""

    finished = serializers.BooleanField(help_text="Always true on success.")
    scout_skill_name = serializers.CharField(help_text="The owner scout's skill name (signals-scout-plan-*).")
    implementation_task_id = serializers.CharField(
        allow_null=True,
        help_text="Id of the auto-started first implementation task, or null when kickoff wasn't "
        "possible (the owner scout starts the work on its next activation instead).",
    )


class InboxPlanImplementationStartedSerializer(serializers.Serializer):
    """Response for a manually started implementation pass."""

    task_id = serializers.CharField(help_text="Id of the implementation task that was created.")
    task_run_id = serializers.CharField(allow_null=True, help_text="Id of the task's initial run, when started.")
    repository = serializers.CharField(help_text="Repository the implementation pass targets.")


class InboxPlanNotReadySerializer(serializers.Serializer):
    """400 response when a plan can't be finished yet."""

    missing = serializers.ListField(
        child=serializers.CharField(),
        help_text="Human-readable labels of what the plan still needs (e.g. title, repository selection).",
    )
