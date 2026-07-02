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
    BaselineEntry,
    BaselineOverview,
    BaselineQuarantineSummary,
    BaselineTotals,
    ClusterSummary,
    CreateRepoInput,
    CreateRunInput,
    CreateRunResult,
    DiffCluster,
    FinalizeResult,
    FinalizeRunRequestInput,
    QuarantinedIdentifierEntry,
    QuarantineInput,
    QuarantineSourceRun,
    RecomputeResult,
    Repo,
    Run,
    RunSummary,
    SetStoryThresholdInput,
    Snapshot,
    SnapshotHistoryEntry,
    SnapshotManifestItem,
    StoryThresholdOverrideEntry,
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
    pixel_threshold_percent = serializers.FloatField(
        read_only=True,
        help_text=(
            "Effective pixel-diff threshold (percent) for this snapshot's story. A snapshot is a pixel-tier "
            "change when its diff percentage reaches this value. Equals the global default unless a per-story "
            "override is set (see `pixel_threshold_overridden`)."
        ),
    )
    structural_threshold_percent = serializers.FloatField(
        read_only=True,
        help_text=(
            "Effective structural (SSIM) threshold expressed as a percentage. A snapshot is a structural-tier "
            "change when its structural difference — `(1 - ssim_score) * 100` — reaches this value. Equals the "
            "global default unless a per-story override is set (see `structural_threshold_overridden`)."
        ),
    )
    pixel_threshold_overridden = serializers.BooleanField(
        read_only=True,
        help_text="Whether the pixel threshold above comes from a per-story override rather than the global default.",
    )
    structural_threshold_overridden = serializers.BooleanField(
        read_only=True,
        help_text="Whether the structural threshold above comes from a per-story override rather than the global default.",
    )

    class Meta:
        dataclass = Snapshot


class RunSerializer(DataclassSerializer):
    approved_by = UserBasicInfoSerializer(allow_null=True, required=False)
    search_match_type = serializers.ChoiceField(
        choices=["exact", "similar"],
        allow_null=True,
        required=False,
        read_only=True,
        help_text=(
            "How this row matched the `search` query parameter: `exact` (the term is a "
            "case-insensitive substring of branch/run type, a commit SHA prefix, or an exact PR "
            "number) or `similar` (a fuzzy trigram match only). Results are ordered exact-first. "
            "Null when the list is not filtered by `search`."
        ),
    )

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


class RecomputeResultSerializer(DataclassSerializer):
    class Meta:
        dataclass = RecomputeResult


class FinalizeResultSerializer(DataclassSerializer):
    class Meta:
        dataclass = FinalizeResult


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
        required=True,
        allow_empty=False,
        help_text=(
            "Snapshots to mark reviewed, each with `identifier` and `new_hash`. This only records the "
            'review in the database (the per-snapshot "Accept change" action) — it does not change the '
            "baseline or the GitHub gate. Commit the baseline and green the gate with the finalize endpoint."
        ),
    )

    class Meta:
        dataclass = ApproveRunRequestInput


class FinalizeRunInputSerializer(DataclassSerializer):
    approve_all = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Approve every still-pending changed and new snapshot before finalizing (tolerated snapshots are "
            "left untouched). Leave false to finalize a run you've already reviewed — finalizing fails if any "
            "changed/new snapshot is still unreviewed."
        ),
    )
    commit_to_github = serializers.BooleanField(
        required=False,
        default=True,
        help_text=(
            "Whether the server commits the approved baseline to the PR branch and greens the gate (the normal "
            "path — leave true). Set false only for tooling that commits the baseline itself: the server skips "
            "the commit and returns the signed YAML in `baseline_content` instead. With false, the gate is NOT "
            "greened and `metadata.baseline_commit_sha` is absent."
        ),
    )
    add_images_to_comment_on_pr = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Whether to embed the before/after snapshot images in the post-approval PR comment. The comment "
            "itself is always posted (when the run was initiated from a GitHub review prompt and the repo has "
            "PR comments enabled); this flag only controls the images. Defaults false — the comment stays a "
            "text summary unless the reviewer opts in to attach the snapshots."
        ),
    )

    class Meta:
        dataclass = FinalizeRunRequestInput


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


class StoryThresholdOverrideEntrySerializer(DataclassSerializer):
    created_by = UserBasicInfoSerializer(allow_null=True, required=False)
    pixel_threshold_percent = serializers.FloatField(
        allow_null=True,
        required=False,
        help_text="Overridden pixel-diff threshold (percent) for this story, or null to use the global default.",
    )
    ssim_dissimilarity_threshold = serializers.FloatField(
        allow_null=True,
        required=False,
        help_text=(
            "Overridden structural (SSIM) threshold as a 0.0-1.0 dissimilarity fraction for this story, or null "
            "to use the global default. A snapshot is structurally changed when `1 - ssim_score` reaches this."
        ),
    )

    class Meta:
        dataclass = StoryThresholdOverrideEntry


class SetStoryThresholdInputSerializer(DataclassSerializer):
    identifier = serializers.CharField(
        max_length=512,
        help_text=(
            "A snapshot identifier from the story. The server strips its theme/viewport/browser tokens to a "
            "story stem, so the override applies to every variant of the story."
        ),
    )
    pixel_threshold_percent = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=100,
        help_text="Pixel-diff threshold (percent) to allow for this story. Null clears it back to the global default.",
    )
    ssim_dissimilarity_threshold = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=1,
        help_text=(
            "Structural (SSIM) threshold as a 0.0-1.0 dissimilarity fraction to allow for this story. "
            "Null clears it back to the global default."
        ),
    )

    class Meta:
        dataclass = SetStoryThresholdInput


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
