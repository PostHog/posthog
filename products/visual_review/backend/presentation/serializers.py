"""
DRF serializers for visual_review.

Converts DTOs to/from JSON using DataclassSerializer.
"""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import (
    AddSnapshotsInput,
    AddSnapshotsResult,
    ApproveRunRequestInput,
    ApproveSnapshotInput,
    Artifact,
    AutoApproveResult,
    BaselineEntry,
    BaselineOverview,
    BaselineQuarantineSummary,
    BaselineTotals,
    ClusterSummary,
    CreateRepoInput,
    CreateRunInput,
    CreateRunResult,
    DiffCluster,
    QuarantinedIdentifierEntry,
    QuarantineInput,
    QuarantineSourceRun,
    RecomputeResult,
    Repo,
    Run,
    RunSummary,
    Snapshot,
    SnapshotHistoryEntry,
    SnapshotManifestItem,
    ToleratedHashEntry,
    UpdateRepoRequestInput,
    UploadTarget,
    UserBasicInfo,
)

# --- Output Serializers ---


class ReviewStateCountsSerializer(serializers.Serializer):
    needs_review = serializers.IntegerField()
    clean = serializers.IntegerField()
    processing = serializers.IntegerField()
    stale = serializers.IntegerField()


class RunSummarySerializer(DataclassSerializer):
    class Meta:
        dataclass = RunSummary


class ArtifactSerializer(DataclassSerializer):
    class Meta:
        dataclass = Artifact


class UserBasicInfoSerializer(DataclassSerializer):
    class Meta:
        dataclass = UserBasicInfo


class DiffClusterSerializer(DataclassSerializer):
    class Meta:
        dataclass = DiffCluster


class ClusterSummarySerializer(DataclassSerializer):
    items = DiffClusterSerializer(many=True)

    class Meta:
        dataclass = ClusterSummary


class SnapshotSerializer(DataclassSerializer):
    # Explicitly mark artifact fields as nullable for OpenAPI schema
    current_artifact = ArtifactSerializer(allow_null=True, required=False)
    baseline_artifact = ArtifactSerializer(allow_null=True, required=False)
    diff_artifact = ArtifactSerializer(allow_null=True, required=False)
    reviewed_by = UserBasicInfoSerializer(allow_null=True, required=False)
    cluster_summary = ClusterSummarySerializer(allow_null=True, required=False)

    class Meta:
        dataclass = Snapshot


class RunSerializer(DataclassSerializer):
    approved_by = UserBasicInfoSerializer(allow_null=True, required=False)

    class Meta:
        dataclass = Run


class RepoSerializer(DataclassSerializer):
    class Meta:
        dataclass = Repo


class UploadTargetSerializer(DataclassSerializer):
    class Meta:
        dataclass = UploadTarget


class CreateRunResultSerializer(DataclassSerializer):
    class Meta:
        dataclass = CreateRunResult


class AutoApproveResultSerializer(DataclassSerializer):
    class Meta:
        dataclass = AutoApproveResult


class RecomputeResultSerializer(DataclassSerializer):
    class Meta:
        dataclass = RecomputeResult


# --- Input Serializers ---


class SnapshotManifestItemSerializer(DataclassSerializer):
    class Meta:
        dataclass = SnapshotManifestItem


class CreateRunInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = CreateRunInput


class AddSnapshotsInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = AddSnapshotsInput


class AddSnapshotsResultSerializer(DataclassSerializer):
    class Meta:
        dataclass = AddSnapshotsResult


class UpdateRepoInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = UpdateRepoRequestInput


class ApproveSnapshotInputSerializer(DataclassSerializer):
    identifier = serializers.CharField(
        help_text="The snapshot identifier to approve (e.g. Storybook story id plus theme).",
    )
    new_hash = serializers.CharField(
        help_text="The content hash of the new baseline image to record for this identifier.",
    )

    class Meta:
        dataclass = ApproveSnapshotInput


class ApproveRunInputSerializer(DataclassSerializer):
    snapshots = ApproveSnapshotInputSerializer(
        many=True,
        required=False,
        help_text=(
            "Specific snapshots to approve, each with `identifier` and `new_hash`. Ignored when `approve_all` is true."
        ),
    )
    approve_all = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Approve every changed and new snapshot in the run. "
            "Mutually exclusive with `snapshots` — pass one or the other."
        ),
    )
    commit_to_github = serializers.BooleanField(
        required=False,
        default=True,
        help_text=(
            "Whether to commit the updated baseline YAML to the PR branch on GitHub. "
            "Set to false to record the approval without pushing a commit."
        ),
    )

    class Meta:
        dataclass = ApproveRunRequestInput

    def validate(self, attrs: ApproveRunRequestInput) -> ApproveRunRequestInput:
        if attrs.approve_all and attrs.snapshots:
            raise serializers.ValidationError(
                {"approve_all": "`approve_all` and `snapshots` are mutually exclusive — pass one or the other."}
            )
        if not attrs.approve_all and not attrs.snapshots:
            raise serializers.ValidationError(
                {"snapshots": "Provide a non-empty `snapshots` list or set `approve_all: true`."}
            )
        return attrs


class SnapshotHistoryEntrySerializer(DataclassSerializer):
    current_artifact = ArtifactSerializer(allow_null=True, required=False)

    class Meta:
        dataclass = SnapshotHistoryEntry


class ToleratedHashEntrySerializer(DataclassSerializer):
    class Meta:
        dataclass = ToleratedHashEntry


class MarkToleratedInputSerializer(serializers.Serializer):
    snapshot_id = serializers.UUIDField(
        help_text=(
            "UUID of the changed snapshot to mark as a known tolerated alternate. "
            "Future runs that produce the same alternate hash for this identifier will not be flagged as changes."
        ),
    )


class QuarantineSourceRunSerializer(DataclassSerializer):
    class Meta:
        dataclass = QuarantineSourceRun


class QuarantinedIdentifierEntrySerializer(DataclassSerializer):
    created_by = UserBasicInfoSerializer(allow_null=True, required=False)
    source_run = QuarantineSourceRunSerializer(
        allow_null=True,
        required=False,
        help_text="Run whose failing snapshot prompted this quarantine. Null when quarantine was created without run context.",
    )

    class Meta:
        dataclass = QuarantinedIdentifierEntry


class BaselineQuarantineSummarySerializer(DataclassSerializer):
    created_by = UserBasicInfoSerializer(allow_null=True, required=False)
    source_run = QuarantineSourceRunSerializer(allow_null=True, required=False)

    class Meta:
        dataclass = BaselineQuarantineSummary


class QuarantineInputSerializer(DataclassSerializer):
    identifier = serializers.CharField(max_length=512, help_text="Snapshot identifier to quarantine.")
    reason = serializers.CharField(max_length=255, help_text="Why this snapshot is being quarantined.")
    source_run_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text=(
            "Optional pointer to the run whose failing snapshot prompted this quarantine — "
            "used to surface a 'view the failing run' link later."
        ),
    )

    class Meta:
        dataclass = QuarantineInput


class UnquarantineQuerySerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=512, help_text="Snapshot identifier to unquarantine")


class CreateRepoInputSerializer(DataclassSerializer):
    class Meta:
        dataclass = CreateRepoInput


class BaselineEntrySerializer(DataclassSerializer):
    quarantine = BaselineQuarantineSummarySerializer(
        allow_null=True,
        required=False,
        help_text="Active quarantine details when `is_quarantined` is true. Null otherwise.",
    )

    class Meta:
        dataclass = BaselineEntry


class BaselineTotalsSerializer(DataclassSerializer):
    by_run_type = serializers.DictField(child=serializers.IntegerField())

    class Meta:
        dataclass = BaselineTotals


class BaselineOverviewSerializer(DataclassSerializer):
    entries = BaselineEntrySerializer(many=True)
    totals = BaselineTotalsSerializer()

    class Meta:
        dataclass = BaselineOverview
