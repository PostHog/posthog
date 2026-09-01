"""
DRF serializers for visual_review.

Converts DTOs to/from JSON using DataclassSerializer.
"""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import (
    FLAKINESS_RATE_DAYS,
    FLAKINESS_WINDOW_DAYS,
    PIXEL_DIFF_THRESHOLD_PERCENT,
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
    hard_count = serializers.IntegerField(
        help_text=(
            f"Default-branch runs in the last {FLAKINESS_RATE_DAYS} days where this snapshot failed "
            "the gate, so somebody could not merge until it was resolved. Counts every result that "
            "is not `unchanged`: a diff over a threshold, a baseline that was never committed or "
            "was dropped, and a baseline whose story no longer renders."
        )
    )
    soft_count = serializers.IntegerField(
        help_text=(
            f"Default-branch runs in the last {FLAKINESS_RATE_DAYS} days where this snapshot "
            "rendered differently from its baseline and a toleration absorbed it, blocking nobody."
        )
    )
    window_runs = serializers.IntegerField(
        help_text=(
            f"Completed default-branch runs of this run type in the last {FLAKINESS_RATE_DAYS} "
            "days. The rate denominator, so a reader can tell 2 failures out of 3 runs from 2 out "
            "of 300."
        )
    )
    hard_rate = serializers.FloatField(
        help_text=(
            "`hard_count` over `window_runs`. The denominator counts every run of this run type, "
            "so a snapshot that only started rendering partway through the window reads lower "
            "than it is."
        )
    )
    soft_rate = serializers.FloatField(help_text="`soft_count` over `window_runs`.")
    last_flaked_at = serializers.DateTimeField(
        allow_null=True,
        required=False,
        help_text=(
            f"Last default-branch run in the last {FLAKINESS_WINDOW_DAYS} days that rendered this "
            "snapshot differently from its baseline, whether the gate failed or a toleration "
            "absorbed it. Reads over the full window rather than the rate span, so a snapshot that "
            "stopped failing still reports when it last did. Null when nothing happened at all."
        ),
    )
    avg_diff_percentage = serializers.FloatField(
        allow_null=True,
        required=False,
        help_text=(
            "Mean fraction of pixels that differed across the live variants. Separates sub-pixel "
            "noise from a small but real rendering change."
        ),
    )
    worst_soft_diff_percentage = serializers.FloatField(
        allow_null=True,
        required=False,
        help_text=(
            f"Largest pixel diff any absorbed run in the last {FLAKINESS_WINDOW_DAYS} days "
            "produced. Reads the full window rather than the rate span, because it asks for the "
            "worst case a snapshot can produce and more days are better evidence of that. Null "
            "when nothing was absorbed."
        ),
    )
    headroom = serializers.FloatField(
        allow_null=True,
        required=False,
        help_text=(
            f"Fraction of the {PIXEL_DIFF_THRESHOLD_PERCENT}% pixel threshold that "
            "`worst_soft_diff_percentage` leaves free. A snapshot is absorbed only while it stays "
            "under the threshold, so this is what says whether it will keep doing so: 1.0 means it "
            "rendered identically every time it was absorbed, 0.0 means it reached the line and "
            "only luck kept it on the passing side. Null when nothing was absorbed, which is not "
            "the same as full headroom."
        ),
    )
    baseline_age_days = serializers.IntegerField(
        allow_null=True,
        required=False,
        help_text=(
            "Days since the first default-branch run that compared against the current baseline, "
            "which is when that baseline took effect. Reads too new for a `broken` snapshot, which "
            "records a change against an unmoved baseline on every run."
        ),
    )
    daily_hard_counts = serializers.ListField(
        child=serializers.IntegerField(),
        help_text=(
            f"Gate-failing runs per day over the last {FLAKINESS_WINDOW_DAYS} days, oldest first. "
            "Always that length, so a fixed time axis can be rendered."
        ),
    )
    daily_soft_counts = serializers.ListField(
        child=serializers.IntegerField(),
        help_text=f"Absorbed runs per day over the same {FLAKINESS_WINDOW_DAYS} days, oldest first.",
    )
    baseline_moved_day_index = serializers.IntegerField(
        allow_null=True,
        required=False,
        help_text=(
            "Index into the daily series where the baseline moved. Null when it moved before the "
            "window opened, which is the common case."
        ),
    )
    flakiness_state = serializers.ChoiceField(
        choices=[(state.value, state.value) for state in FlakinessState],
        help_text=(
            "An urgency ladder, where each rung asks for a different fix. `broken` fails nearly "
            "every run, so its baseline is wrong and quarantining it only hides that. `unstable` "
            "fails some runs and not others, the classic flake. `at_risk` never fails, but its "
            "worst absorbed diff is already touching the threshold, so the next unrelated change "
            "turns it red. `noisy` renders variants and absorbs them with room to spare. `clean` "
            "matched its baseline on every run in the window."
        ),
    )
    needs_decision = serializers.BooleanField(
        help_text=(
            "True when an active quarantine has run out, is about to, or covers a snapshot that "
            "has stopped failing the gate. All three mean a human has to extend it or lift it."
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
    broken = serializers.IntegerField(help_text="Identifiers whose `flakiness_state` is `broken`.")
    unstable = serializers.IntegerField(help_text="Identifiers whose `flakiness_state` is `unstable`.")
    at_risk = serializers.IntegerField(help_text="Identifiers whose `flakiness_state` is `at_risk`.")
    noisy = serializers.IntegerField(help_text="Identifiers whose `flakiness_state` is `noisy`.")
    clean = serializers.IntegerField(
        help_text=(
            "Identifiers whose `flakiness_state` is `clean`. They are listed because they carry live "
            "variants or older history, and reported here so every listed entry is reachable."
        )
    )
    by_run_type = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Listed identifiers per run type, so one suite's noise can be told from another's.",
    )

    class Meta:
        dataclass = FlakinessTotals


class FlakinessOverviewSerializer(DataclassSerializer):
    entries = FlakinessEntrySerializer(many=True)
    totals = FlakinessTotalsSerializer()

    class Meta:
        dataclass = FlakinessOverview
