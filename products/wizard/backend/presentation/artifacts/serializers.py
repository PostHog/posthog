from typing import cast

from drf_spectacular.utils import PolymorphicProxySerializer
from rest_framework import serializers

from products.wizard.backend.facade.contracts import (
    WizardRunArtifactDTO,
    WizardRunGitDiffArtifactDTO,
    WizardRunPullRequestArtifactDTO,
)
from products.wizard.backend.facade.enums import WizardRunArtifactType


class WizardRunArtifactSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique ID of the run artifact.")
    team_id = serializers.IntegerField(read_only=True, help_text="Project that owns the run artifact.")
    run_id = serializers.UUIDField(read_only=True, help_text="Wizard run that produced the artifact.")


class WizardRunGitDiffArtifactSerializer(WizardRunArtifactSerializer):
    artifact_type = serializers.ChoiceField(
        read_only=True,
        choices=[WizardRunArtifactType.GIT_DIFF.value],
        help_text="Format of the changes produced by the run.",
    )
    size_bytes = serializers.IntegerField(read_only=True, help_text="Stored artifact size in bytes.")
    content_hash = serializers.CharField(read_only=True, help_text="SHA-256 hash of the stored artifact content.")
    additions = serializers.IntegerField(
        read_only=True, allow_null=True, help_text="Number of added lines in the diff."
    )
    removals = serializers.IntegerField(
        read_only=True, allow_null=True, help_text="Number of removed lines in the diff."
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="Time when the artifact was stored.")


class WizardRunPullRequestArtifactSerializer(WizardRunArtifactSerializer):
    artifact_type = serializers.ChoiceField(
        read_only=True,
        choices=[WizardRunArtifactType.PULL_REQUEST.value],
        help_text="Format of the changes produced by the run.",
    )
    url = serializers.URLField(read_only=True, help_text="GitHub URL of the pull request.")
    number = serializers.IntegerField(read_only=True, help_text="Repository-local pull request number.")
    repository = serializers.CharField(read_only=True, help_text="GitHub repository in owner/name format.")
    head_branch = serializers.CharField(read_only=True, help_text="Branch containing the setup agent's changes.")
    base_branch = serializers.CharField(read_only=True, help_text="Branch that the pull request targets.")
    created_at = serializers.DateTimeField(read_only=True, help_text="Time when the artifact was stored.")


WizardRunArtifactSchema = PolymorphicProxySerializer(
    component_name="WizardRunArtifact",
    serializers={
        WizardRunArtifactType.GIT_DIFF.value: WizardRunGitDiffArtifactSerializer,
        WizardRunArtifactType.PULL_REQUEST.value: WizardRunPullRequestArtifactSerializer,
    },
    resource_type_field_name="artifact_type",
    many=True,
)


def serialize_wizard_run_artifact(artifact: WizardRunArtifactDTO) -> dict[str, object]:
    if isinstance(artifact, WizardRunGitDiffArtifactDTO):
        return cast(dict[str, object], WizardRunGitDiffArtifactSerializer(artifact).data)
    if isinstance(artifact, WizardRunPullRequestArtifactDTO):
        return cast(dict[str, object], WizardRunPullRequestArtifactSerializer(artifact).data)
    raise TypeError("Unsupported Wizard run artifact")
