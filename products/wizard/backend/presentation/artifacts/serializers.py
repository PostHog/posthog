from typing import cast

from drf_spectacular.utils import PolymorphicProxySerializer
from rest_framework import serializers

from products.wizard.backend.facade.contracts import (
    WizardRunArtifactDTO,
    WizardRunGitDiffArtifactDTO,
    WizardRunNotebookArtifactDTO,
    WizardRunPullRequestArtifactDTO,
    WizardRunSpendProjectionArtifactDTO,
)
from products.wizard.backend.facade.enums import WizardRunArtifactType, WizardSpendEffort, WizardSpendFixLocation


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


class WizardRunNotebookArtifactSerializer(WizardRunArtifactSerializer):
    artifact_type = serializers.ChoiceField(
        read_only=True,
        choices=[WizardRunArtifactType.NOTEBOOK.value],
        help_text="Format of the changes produced by the run.",
    )
    short_id = serializers.CharField(read_only=True, help_text="Short ID of the notebook the run created.")
    dashboard_ids = serializers.ListField(
        child=serializers.IntegerField(),
        read_only=True,
        help_text="IDs of the dashboards the run created in the project.",
    )
    insight_ids = serializers.ListField(
        child=serializers.IntegerField(),
        read_only=True,
        help_text="IDs of the insights the run created in the project.",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="Time when the artifact was stored.")


class WizardSpendRangeSerializer(serializers.Serializer):
    low = serializers.FloatField(read_only=True, help_text="Lower end of the range.")
    high = serializers.FloatField(read_only=True, help_text="Upper end of the range.")


class WizardSpendProjectionItemSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True, help_text="Stable ID of the recommendation within the run.")
    title = serializers.CharField(read_only=True, help_text="What to change, in one line.")
    billing_type = serializers.CharField(read_only=True, help_text="Billed product or add-on the change reduces.")
    unit = serializers.CharField(read_only=True, help_text="Billable unit of the volume, such as events.")
    volume_before = serializers.FloatField(read_only=True, help_text="Measured monthly volume before the change.")
    volume_after = WizardSpendRangeSerializer(read_only=True, help_text="Expected monthly volume after the change.")
    saving_monthly = WizardSpendRangeSerializer(
        read_only=True, help_text="Monthly saving in USD, priced from the organization's billing tiers."
    )
    evidence = serializers.CharField(read_only=True, help_text="The measurement the saving is based on.")
    tradeoff = serializers.CharField(read_only=True, help_text="What the customer gives up with the change.")
    effort = serializers.ChoiceField(
        read_only=True,
        choices=WizardSpendEffort.choices,
        help_text="Kind of work the change takes: code, a setting, or billing.",
    )
    fixed_in = serializers.ChoiceField(
        read_only=True,
        choices=WizardSpendFixLocation.choices,
        help_text="Where the change is made: the pull request or the notebook.",
    )


class WizardRunSpendProjectionArtifactSerializer(WizardRunArtifactSerializer):
    artifact_type = serializers.ChoiceField(
        read_only=True,
        choices=[WizardRunArtifactType.SPEND_PROJECTION.value],
        help_text="Format of the changes produced by the run.",
    )
    currency = serializers.CharField(read_only=True, help_text="Currency of every amount. Always USD.")
    baseline_monthly = serializers.FloatField(
        read_only=True, help_text="Projected monthly bill of the organization before the changes."
    )
    saving_monthly = WizardSpendRangeSerializer(
        read_only=True, help_text="Projected monthly saving if every recommendation ships."
    )
    items = WizardSpendProjectionItemSerializer(
        many=True, read_only=True, help_text="Recommendations ordered by saving, largest first."
    )
    priced_at = serializers.DateTimeField(read_only=True, help_text="Time when the savings were priced.")
    created_at = serializers.DateTimeField(read_only=True, help_text="Time when the artifact was stored.")


WizardRunArtifactSchema = PolymorphicProxySerializer(
    component_name="WizardRunArtifact",
    serializers={
        WizardRunArtifactType.GIT_DIFF.value: WizardRunGitDiffArtifactSerializer,
        WizardRunArtifactType.PULL_REQUEST.value: WizardRunPullRequestArtifactSerializer,
        WizardRunArtifactType.NOTEBOOK.value: WizardRunNotebookArtifactSerializer,
        WizardRunArtifactType.SPEND_PROJECTION.value: WizardRunSpendProjectionArtifactSerializer,
    },
    resource_type_field_name="artifact_type",
    many=True,
)


def serialize_wizard_run_artifact(artifact: WizardRunArtifactDTO) -> dict[str, object]:
    if isinstance(artifact, WizardRunGitDiffArtifactDTO):
        return cast(dict[str, object], WizardRunGitDiffArtifactSerializer(artifact).data)
    if isinstance(artifact, WizardRunPullRequestArtifactDTO):
        return cast(dict[str, object], WizardRunPullRequestArtifactSerializer(artifact).data)
    if isinstance(artifact, WizardRunNotebookArtifactDTO):
        return cast(dict[str, object], WizardRunNotebookArtifactSerializer(artifact).data)
    if isinstance(artifact, WizardRunSpendProjectionArtifactDTO):
        return cast(dict[str, object], WizardRunSpendProjectionArtifactSerializer(artifact).data)
    raise TypeError("Unsupported Wizard run artifact")
