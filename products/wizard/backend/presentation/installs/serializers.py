from rest_framework import serializers

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.enums import WizardRunStage, WizardRunStatus, WizardTaskStatus
from products.wizard.backend.facade.errors import InvalidBranchError, InvalidRepositoryError


class WizardInstallStartRequestSerializer(serializers.Serializer):
    repository = serializers.CharField(
        allow_blank=False,
        max_length=255,
        help_text=(
            "GitHub repository to set up, in owner/name format. The project's GitHub connection must have access to it."
        ),
    )
    branch = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=255,
        help_text="Branch to start from and to open the pull request against. Defaults to the repository's default branch.",
    )
    idempotency_key = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=255,
        help_text="Unique key for this request. A retry with the same key returns the same run instead of starting another.",
    )

    def validate_repository(self, value: str) -> str:
        repository = value.strip()
        try:
            wizard_facade.validate_git_repository(repository)
        except InvalidRepositoryError:
            raise serializers.ValidationError("Enter a repository in owner/name format.")
        return repository

    def validate_branch(self, value: str) -> str:
        branch = value.strip()
        try:
            wizard_facade.validate_git_branch(branch)
        except InvalidBranchError:
            raise serializers.ValidationError("Enter a valid branch name, such as main.")
        return branch


class WizardInstallStartSerializer(serializers.Serializer):
    run_id = serializers.UUIDField(read_only=True, help_text="ID of the setup run. Pass it to the status endpoint.")
    status = serializers.ChoiceField(
        read_only=True,
        choices=WizardRunStatus.choices,
        help_text="Current lifecycle status of the setup run.",
    )
    url = serializers.URLField(read_only=True, help_text="PostHog page where the user can follow their setup runs.")


class WizardInstallTaskSerializer(serializers.Serializer):
    name = serializers.CharField(source="title", read_only=True, help_text="Task the setup agent planned.")
    status = serializers.ChoiceField(
        read_only=True,
        choices=WizardTaskStatus.choices,
        help_text="Current task status reported by the setup agent.",
    )


class WizardInstallStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        source="run.status",
        read_only=True,
        choices=WizardRunStatus.choices,
        help_text="Lifecycle status of the setup run. created and running mean it is still in progress.",
    )
    stage = serializers.ChoiceField(
        source="run.stage",
        read_only=True,
        allow_null=True,
        choices=WizardRunStage.choices,
        help_text="Step the setup run is on while it is in progress, or null otherwise.",
    )
    error_code = serializers.CharField(
        source="run.error_code",
        read_only=True,
        allow_null=True,
        help_text="Machine-readable failure reason, or null if the run has not failed.",
    )
    error_message = serializers.CharField(
        source="run.error_message",
        read_only=True,
        allow_null=True,
        help_text="Failure explanation, or null if the run has not failed.",
    )
    pull_request_url = serializers.URLField(
        read_only=True,
        allow_null=True,
        help_text="Pull request with the setup changes, or null until the run opens one.",
    )
    tasks = WizardInstallTaskSerializer(
        source="run.tasks",
        many=True,
        read_only=True,
        help_text="Tasks the setup agent planned, in order.",
    )
    next_step = serializers.CharField(
        read_only=True, help_text="What happens next, in a sentence to relay to the user."
    )
