"""
DRF serializers for visual_review.

Converts DTOs to/from JSON using DataclassSerializer.
"""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import (
    FLAKINESS_STRIP_DAYS,
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
    FlakinessEntry,
    FlakinessOverview,
    FlakinessTotals,
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
from ..facade.enums import FlakinessState

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
    search_match_type = serializers.ChoiceField(
        choices=["exact", "similar"],
        allow_null=True,
        required=False,
        read_only=True,
        help_text=(
            "How this row matched the `search` query parameter: `exact` (the term is a "
            "case-insensitive substring of branch/run type, a commit SHA prefix, or an exact PR "
            "number) or `similar` (a fuzzy trigram match, returned only when no exact match "
            "exists). Null when the list is not filtered by `search`."
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


class FlakinessEntrySerializer(DataclassSerializer):
    variant_count = serializers.IntegerField(
        help_text=(
            "Distinct alternate hashes the classifier can still match for this snapshot's current "
            "baseline. Reads as how many different images this snapshot is currently allowed to "
            "produce. Resets when the baseline moves, because tolerations recorded against an old "
            "baseline hash can never match again."
        )
    )
    last_flaked_at = serializers.DateTimeField(
        allow_null=True,
        required=False,
        help_text=(
            "Last default-branch run that rendered one of those variants. This is not when a variant "
            "was first recorded: a snapshot can cycle through variants it already recorded without "
            "adding a new one, and that case still flakes on every run. Null when no run matched one."
        ),
    )
    avg_diff_percentage = serializers.FloatField(
        allow_null=True,
        required=False,
        help_text=(
            "Mean fraction of pixels that differed across those variants. Separates sub-pixel noise "
            "from a small but real rendering change."
        ),
    )
    baseline_age_days = serializers.IntegerField(
        allow_null=True,
        required=False,
        help_text=(
            "Days since the first default-branch run that compared against the current baseline, "
            "which is when that baseline took effect. Context for `variant_count`: the same count "
            "against a four-day-old baseline is far worse than against a six-month-old one."
        ),
    )
    daily_variant_counts = serializers.ListField(
        child=serializers.IntegerField(),
        help_text=(
            f"Variants recorded per day over the last {FLAKINESS_STRIP_DAYS} days, oldest first. "
            "Always that length, so a fixed time axis can be rendered."
        ),
    )
    baseline_moved_day_index = serializers.IntegerField(
        allow_null=True,
        required=False,
        help_text=(
            "Index into `daily_variant_counts` where the baseline moved. Null when it moved before "
            "the window opened, which is the common case."
        ),
    )
    flakiness_state = serializers.ChoiceField(
        choices=[(state.value, state.value) for state in FlakinessState],
        help_text=(
            "`unstable` when a run rendered a variant inside the recency window, new or already "
            "known, `settled` when variants exist against this baseline but none recently, "
            "`clean` when none exist. A `clean` entry is always a quarantined one, because an "
            "unquarantined snapshot with no variants is not listed at all."
        ),
    )
    needs_decision = serializers.BooleanField(
        help_text=(
            "True when an active quarantine has run out, is about to, or covers a snapshot that no "
            "longer produces variants. All three mean a human has to extend it or lift it."
        )
    )
    quarantine = BaselineQuarantineSummarySerializer(
        allow_null=True,
        required=False,
        help_text="Active quarantine details when `is_quarantined` is true. Null otherwise.",
    )

    class Meta:
        dataclass = FlakinessEntry


class FlakinessTotalsSerializer(DataclassSerializer):
    listed = serializers.IntegerField(help_text="Identifiers with an entry in `entries`.")
    tracked = serializers.IntegerField(
        help_text=(
            "Identifiers with a current baseline, listed or not. The denominator that says how much "
            "of the repo renders consistently."
        )
    )
    by_run_type = serializers.DictField(child=serializers.IntegerField())

    class Meta:
        dataclass = FlakinessTotals


class FlakinessOverviewSerializer(DataclassSerializer):
    entries = FlakinessEntrySerializer(many=True)
    totals = FlakinessTotalsSerializer()

    class Meta:
        dataclass = FlakinessOverview
