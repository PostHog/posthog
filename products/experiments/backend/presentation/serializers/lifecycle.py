"""Request and response serializers for the lifecycle and copy actions of an experiment."""

from rest_framework import serializers


class EndExperimentSerializer(serializers.Serializer):
    conclusion = serializers.ChoiceField(
        choices=["won", "lost", "inconclusive", "stopped_early", "invalid"],
        required=False,
        allow_null=True,
        help_text="The conclusion of the experiment.",
    )
    conclusion_comment = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=4000,
        help_text="Optional comment about the experiment conclusion.",
    )
    open_cleanup_pr = serializers.BooleanField(
        default=False,
        help_text=(
            "When true, open a draft pull request that removes the experiment's feature-flag code "
            "from the linked repository. A personal API key needs the task:write scope (403 otherwise). "
            "Skipped when the conclusion is empty, or when no connected repository can be resolved."
        ),
    )
    repository = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=255,
        help_text=(
            "GitHub repository to open the cleanup pull request in, in `organization/repository` format. "
            "Only used when open_cleanup_pr is true. It must be one of the team's connected repositories "
            "(see the flag_cleanup_target action); it is then saved as the experiment's repository. When "
            "omitted, the experiment's saved repository, the team's default cleanup repository, or the "
            "team's only connected repository is used."
        ),
    )
    set_repository_as_team_default = serializers.BooleanField(
        default=False,
        help_text=(
            "When true, also save `repository` as this environment's default cleanup repository, used for "
            "experiments that have no repository of their own. Only acts when open_cleanup_pr is true and "
            "`repository` is provided and belongs to the team's GitHub installation. Requires project admin "
            "access (403 otherwise)."
        ),
    )

    def validate_repository(self, value: str | None) -> str | None:
        if not value:
            return None
        parts = value.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise serializers.ValidationError("Repository must be in the format organization/repository")
        return value.lower()


class ExperimentFlagCleanupTaskSerializer(serializers.Serializer):
    task_id = serializers.UUIDField(help_text="ID of the flag-cleanup Desktop task.")
    run_status = serializers.ChoiceField(
        choices=["not_started", "queued", "in_progress", "completed", "failed", "cancelled"],
        help_text="Status of the task's latest run.",
    )
    is_terminal = serializers.BooleanField(
        help_text="Whether the run has finished (successfully or not). Stop polling once true."
    )
    pr_url = serializers.CharField(
        allow_null=True,
        help_text="URL of the pull request the task opened, when it opened one.",
    )
    can_view_task = serializers.BooleanField(
        help_text=(
            "Whether the requesting user can open the task in PostHog Desktop. Cleanup tasks are "
            "visible to their creator only, so other viewers should not be shown a task link."
        ),
    )


class ExperimentFlagCleanupTargetSerializer(serializers.Serializer):
    repository = serializers.CharField(
        allow_null=True,
        help_text="Repository a flag-cleanup pull request would be opened in, or null when none can be determined.",
    )
    source = serializers.ChoiceField(  # type: ignore[assignment]  # field named `source` shadows DRF Field.source
        choices=["explicit", "team_default", "single_repo", "ambiguous", "no_integration"],
        help_text=(
            "How the repository was determined: `explicit` (saved on the experiment), `team_default` (the "
            "environment's default cleanup repository), `single_repo` (the team's only connected repository), "
            "`ambiguous` (several connected repositories and none saved — pass one via repository on "
            "end/ship_variant), or `no_integration` (no GitHub integration or no "
            "connected repositories, so no cleanup PR can be opened)."
        ),
    )
    candidates = serializers.ListField(
        child=serializers.CharField(),
        help_text="Repositories connected to the team's GitHub integration, to choose a target from.",
    )


class ArchiveExperimentSerializer(serializers.Serializer):
    disable_feature_flag = serializers.BooleanField(
        default=False,
        help_text=(
            "When the linked feature flag is still enabled, also disable and archive it along with "
            "the experiment. Has no effect if the flag is already disabled (it is archived either way)."
        ),
    )


class ShipVariantSerializer(EndExperimentSerializer):
    variant_key = serializers.CharField(help_text="The key of the variant to ship.")
    release_to_everyone = serializers.BooleanField(
        default=False,
        help_text=(
            "If true, prepend a release condition to the feature flag that rolls the variant out to 100% of users, "
            "overriding any existing release conditions on the flag. If false (default), only update the variant "
            "distribution — existing release conditions are preserved and the variant is served only to users who "
            "already match them."
        ),
    )


class CopyExperimentToProjectSerializer(serializers.Serializer):
    target_team_id = serializers.IntegerField(help_text="The team ID to copy the experiment to.")
    feature_flag_key = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional feature flag key to use in the destination team.",
    )
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional name for the copied experiment.",
    )
