from rest_framework import serializers

from products.signals.backend.models import SignalReport


class InboxFeatureReportSerializer(serializers.ModelSerializer):
    """List representation of a feature report.

    A feature is an ordinary `SignalReport` surfaced in the Features tab. This serializer exposes
    only the fields the list needs.
    """

    # Declared as a plain string rather than the model's `Status` ChoiceField on purpose: a bare
    # `status` enum collides with other `status` choice sets under drf-spectacular's `--fail-on-warn`
    # (see the improving-drf-endpoints skill). It's read-only here, so a string is all the list needs.
    status = serializers.CharField(
        read_only=True,
        help_text="Report lifecycle status (e.g. ready, resolved, suppressed).",
    )
    is_planning = serializers.SerializerMethodField(
        help_text="Whether the feature is still in its initial planning phase."
    )

    def get_is_planning(self, obj: SignalReport) -> bool:
        # The list view precomputes this from the completion marker so serialization does not issue
        # one artefact query per feature.
        planning_report_ids: set[str] = self.context.get("planning_report_ids", set())
        return str(obj.id) in planning_report_ids

    class Meta:
        model = SignalReport
        fields = [
            "id",
            "title",
            "summary",
            "status",
            "is_planning",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "title": {"help_text": "The feature's title. Placeholder while planning begins."},
            "summary": {"help_text": "The feature's current summary, seeded from the initial description."},
            "created_at": {"help_text": "When the feature report was created."},
            "updated_at": {"help_text": "When the feature report was last updated."},
        }


class InboxFeatureCreateSerializer(serializers.Serializer):
    """Body for creating a feature from the user's initial idea."""

    initial_description = serializers.CharField(
        max_length=4000,
        allow_blank=False,
        help_text="A brief description of the feature. Seeds its summary and the planning agent's first message.",
    )


class InboxFeatureCreatedSerializer(serializers.Serializer):
    """Response for a created feature and its planning conversation."""

    report_id = serializers.CharField(help_text="The new feature report's id.")
    task_id = serializers.CharField(help_text="The planning conversation's task id.")
    run_id = serializers.CharField(
        allow_null=True, help_text="The planning conversation's initial run id, when already started."
    )


class InboxFeaturePlanningFinishedSerializer(serializers.Serializer):
    """Response when a feature completes its initial planning phase."""

    planning_finished = serializers.BooleanField(help_text="Always true on success.")
    scout_skill_name = serializers.CharField(help_text="The feature owner scout's skill name.")
    implementation_task_id = serializers.CharField(
        allow_null=True,
        help_text="Id of the auto-started first implementation task, or null when kickoff wasn't "
        "possible (the owner scout starts the work on its next activation instead).",
    )


class InboxFeatureImplementationStartedSerializer(serializers.Serializer):
    """Response for a manually started implementation pass."""

    task_id = serializers.CharField(help_text="Id of the implementation task that was created.")
    task_run_id = serializers.CharField(allow_null=True, help_text="Id of the task's initial run, when started.")
    repository = serializers.CharField(help_text="Repository the implementation pass targets.")


class InboxFeaturePlanningNotReadySerializer(serializers.Serializer):
    """400 response when the feature cannot complete planning yet."""

    missing = serializers.ListField(
        child=serializers.CharField(),
        help_text="Labels for feature details that planning still needs, such as title or repository selection.",
    )
