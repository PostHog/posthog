import re

from rest_framework import serializers

from products.signals.backend.artefact_schemas import FeatureStage
from products.signals.backend.models import FeatureDiscoveryRun, SignalReport

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


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
    feature_stage = serializers.SerializerMethodField(
        help_text="Feature ownership stage: staged, planning, or managed."
    )

    def get_is_planning(self, obj: SignalReport) -> bool:
        # The list view precomputes lifecycle state so serialization does not issue one query per feature.
        return self.get_feature_stage(obj) == FeatureStage.PLANNING

    def get_feature_stage(self, obj: SignalReport) -> str:
        feature_stages: dict[str, FeatureStage] = self.context.get("feature_stages", {})
        return feature_stages.get(str(obj.id), FeatureStage.PLANNING).value

    class Meta:
        model = SignalReport
        fields = [
            "id",
            "title",
            "summary",
            "status",
            "is_planning",
            "feature_stage",
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


class InboxFeatureDiscoveryCreateSerializer(serializers.Serializer):
    repository = serializers.CharField(
        max_length=512,
        help_text="GitHub repository to explore in owner/repo format.",
    )
    focus = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=4000,
        help_text="Optional direction that limits which features the agent discovers.",
    )

    def validate_repository(self, value: str) -> str:
        normalized = value.strip()
        if not _REPOSITORY_RE.fullmatch(normalized):
            raise serializers.ValidationError("Select a repository in owner/repo format.")
        return normalized


class InboxFeatureDiscoveryCreatedSerializer(serializers.Serializer):
    run_id = serializers.UUIDField(help_text="Id of the queued feature discovery run.")


class InboxFeatureDiscoveryRunSerializer(serializers.ModelSerializer):
    discovery_status = serializers.CharField(
        source="status",
        read_only=True,
        help_text="Current discovery state: queued, running, completed, or failed.",
    )
    task_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text="Agent task used for the discovery session, when started.",
    )

    class Meta:
        model = FeatureDiscoveryRun
        fields = [
            "id",
            "repository",
            "focus",
            "discovery_status",
            "discovered_count",
            "error",
            "task_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "repository": {"help_text": "GitHub repository explored by the agent."},
            "focus": {"help_text": "Direction used to limit discovery, or an empty string for all features."},
            "discovered_count": {"help_text": "Number of staged features produced after completion."},
            "error": {"help_text": "Failure message with the next action, or an empty string."},
            "created_at": {"help_text": "When discovery was requested."},
            "updated_at": {"help_text": "When discovery last changed state."},
        }


class InboxFeatureErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="What happened and what to do next.")
