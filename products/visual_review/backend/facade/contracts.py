"""
Contract types for visual_review.

Stable, framework-free frozen dataclasses that define what this product
exposes to the rest of the codebase. No Django imports.

These use ``pydantic.dataclasses.dataclass`` rather than the stdlib variant — same
syntax, same ``is_dataclass()`` compatibility (so ``DataclassSerializer`` keeps
working), but with runtime validation on construction. Pydantic v2 coerces where
the conversion is unambiguous (string→UUID/datetime, int→str) and raises
``ValidationError`` otherwise, so structural mistakes from mappers or internal
callers (None for a required int, a dict where a list is expected, an
unparseable UUID) surface at the facade boundary instead of producing a
malformed JSON payload twelve stack frames later.
"""

from dataclasses import field
from datetime import datetime
from uuid import UUID

from pydantic.dataclasses import dataclass

# Two-tier classification thresholds, applied by `diffing.classify_compare_result`:
#
# 1. Pixel diff ratio — fast path for obvious changes. Snapshots above
#    this are immediately classified as CHANGED.
# 2. SSIM perceptual threshold — safety net for tall-page dilution. A real UI
#    change at the bottom of a long screenshot affects few pixels but produces
#    a measurable structural shift that SSIM catches.
#
# Only when both are below threshold is the snapshot reclassified as UNCHANGED.
#
# They live here rather than next to the classifier because they are also what
# `FlakinessEntry.headroom` is measured against, so a consumer reading that
# field needs them. Importing the classifier instead would pull the image
# libraries onto the web request path.
PIXEL_DIFF_THRESHOLD_PERCENT = 2.5
SSIM_DISSIMILARITY_THRESHOLD = 0.01  # 1% structural difference

# --- Input DTOs ---


@dataclass(frozen=True)
class SnapshotManifestItem:
    """A single snapshot in a CI manifest."""

    identifier: str
    content_hash: str
    width: int | None = None
    height: int | None = None
    # Flexible metadata (browser, viewport, is_critical, etc.)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CreateRunInput:
    """Input for creating a new visual review run."""

    repo_id: UUID
    run_type: str
    commit_sha: str
    branch: str
    snapshots: list[SnapshotManifestItem]
    pr_number: int | None = None
    # Deprecated: backend fetches baselines from GitHub. Kept for old CLI compat.
    baseline_hashes: dict[str, str] = field(default_factory=dict)
    # Deprecated: backend computes from RunSnapshot rows at complete time.
    unchanged_count: int = 0
    removed_identifiers: list[str] = field(default_factory=list)
    purpose: str = "review"
    # Run-level metadata (pr_title, ci_job_url, base_branch, etc.)
    metadata: dict = field(default_factory=dict)
    # True when CI only rendered a subset of the suite.
    # Tells the classifier to leave omitted baseline identifiers alone instead
    # of marking them as removed.
    is_partial: bool = False


@dataclass(frozen=True)
class CreateRepoInput:
    """Input for creating a repo. repo_external_id resolved server-side if omitted."""

    repo_full_name: str
    repo_external_id: int | None = None


@dataclass(frozen=True)
class ApproveSnapshotInput:
    """A snapshot approval from the UI."""

    identifier: str
    new_hash: str


@dataclass(frozen=True)
class ApproveRunRequestInput:
    """Request body for marking snapshots reviewed (DB only). run_id and user_id come from URL and auth."""

    snapshots: list[ApproveSnapshotInput] = field(default_factory=list)


@dataclass(frozen=True)
class ApproveRunInput:
    """Full input for marking snapshots reviewed (internal use)."""

    run_id: UUID
    user_id: int
    snapshots: list[ApproveSnapshotInput]


@dataclass(frozen=True)
class FinalizeRunRequestInput:
    """Request body for finalizing a run. run_id and user_id come from URL and auth."""

    approve_all: bool = False
    commit_to_github: bool = True
    add_images_to_comment_on_pr: bool = False


# --- Output DTOs ---


@dataclass(frozen=True)
class UploadTarget:
    """Upload target for a single artifact."""

    content_hash: str
    url: str
    fields: dict[str, str]


@dataclass(frozen=True)
class AddSnapshotsInput:
    """Batch of snapshots to add to an existing run (shard-based flow)."""

    snapshots: list[SnapshotManifestItem]
    baseline_hashes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AddSnapshotsResult:
    """Result of adding snapshots to a run."""

    added: int
    uploads: list[UploadTarget]


@dataclass(frozen=True)
class CreateRunResult:
    """Result of creating a run."""

    run_id: UUID
    uploads: list[UploadTarget]


@dataclass(frozen=True)
class Artifact:
    """An artifact in the system."""

    id: UUID
    content_hash: str
    width: int | None
    height: int | None
    download_url: str | None


@dataclass(frozen=True)
class UserBasicInfo:
    """Lightweight user info for display purposes."""

    id: int
    first_name: str
    email: str


@dataclass(frozen=True)
class DiffCluster:
    """One connected region of differing pixels in a snapshot diff.

    Wire shape — verbose key names for frontend consumption. Storage uses
    a compact form (see `diff_metadata.DiffCluster`).
    """

    x: int
    y: int
    width: int
    height: int
    pixel_count: int
    centroid_x: float
    centroid_y: float


@dataclass(frozen=True)
class ClusterSummary:
    """Spatial clustering of differing pixels for a snapshot.

    `total` is the count before any per-snapshot cap (so the FE can show
    "+N more" or pick a categorical label like 'Perceptible change' for highly
    scattered diffs even when only the top-N items are shipped).
    `truncated` is True when `len(items) < total`.
    """

    items: list[DiffCluster]
    total: int
    truncated: bool


@dataclass(frozen=True)
class Snapshot:
    """A snapshot with its comparison results."""

    id: UUID
    run_id: UUID
    identifier: str
    result: str
    classification_reason: str  # exact, tolerated_hash, below_threshold, or ""
    current_artifact: Artifact | None
    baseline_artifact: Artifact | None
    diff_artifact: Artifact | None
    diff_percentage: float | None
    diff_pixel_count: int | None
    # Review state (human decision, separate from computed result)
    review_state: str  # pending, approved, (future: rejected)
    reviewed_at: datetime | None
    approved_hash: str
    tolerated_hash_id: UUID | None = None
    is_quarantined: bool = False
    reviewed_by: UserBasicInfo | None = None
    # Flexible metadata (browser, viewport, is_critical, is_flaky, page_group, etc.)
    metadata: dict = field(default_factory=dict)
    # Diff classification details — see ChangeKind enum and the diff
    # pipeline. `change_kind` is the categorical signal the UI renders
    # ('pixel' / 'structural'); `ssim_score` and `cluster_summary` are
    # details available alongside. `size_mismatch` flags the case where
    # baseline and current had different dimensions (composes with any
    # change_kind — pixelhog padded the smaller image and ran metrics
    # against the padded buffers).
    ssim_score: float | None = None
    change_kind: str = ""
    cluster_summary: ClusterSummary | None = None
    size_mismatch: bool = False


@dataclass(frozen=True)
class RunSnapshots:
    """A run's snapshots plus the count of its currently-quarantined identifiers.

    `quarantined_count` always reflects the full run regardless of whether
    quarantined snapshots were filtered out of `snapshots`, so callers can
    surface "N hidden" without a second fetch.
    """

    snapshots: list[Snapshot]
    quarantined_count: int


@dataclass(frozen=True)
class RunSummary:
    """Summary stats for a run."""

    total: int
    changed: int
    new: int
    removed: int
    unchanged: int
    unresolved: int = 0
    tolerated_matched: int = 0


@dataclass(frozen=True)
class Run:
    """A visual review run."""

    id: UUID
    repo_id: UUID
    status: str
    run_type: str
    commit_sha: str
    branch: str
    pr_number: int | None
    approved: bool
    approved_at: datetime | None
    summary: RunSummary
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    is_stale: bool = False
    superseded_by_id: UUID | None = None
    approved_by: UserBasicInfo | None = None
    # Flexible metadata (pr_title, ci_job_url, base_branch, etc.)
    metadata: dict = field(default_factory=dict)
    # How this row matched the `search` query param: "exact", "similar", or None when not searching.
    search_match_type: str | None = None


@dataclass(frozen=True)
class FinalizeResult:
    """Result of finalizing a run: the run plus the signed baseline YAML.

    ``baseline_content`` is populated only when ``commit_to_github=False`` (the caller commits
    the baseline itself); it is empty when the server already committed it to the PR branch.
    """

    run: Run
    baseline_content: str


@dataclass(frozen=True)
class RecomputeResult:
    """Result of re-evaluating quarantine/counts and optionally retriggering CI."""

    run: Run
    counts_changed: bool
    unresolved: int
    ci_rerun_triggered: bool
    ci_rerun_error: str | None = None


@dataclass(frozen=True)
class ToleratedHashEntry:
    """A known tolerated alternate hash for a snapshot identifier."""

    id: UUID
    alternate_hash: str
    baseline_hash: str
    reason: str
    diff_percentage: float | None
    created_at: datetime
    source_run_id: UUID | None


@dataclass(frozen=True)
class QuarantineSourceRun:
    """Pointer back to the run whose failing snapshot prompted a quarantine.

    Enough fields to render a "View the failing run" link without a second
    fetch: the run id for routing, plus branch / commit / PR / time for the
    one-liner the UI shows above the link.
    """

    id: UUID
    branch: str
    commit_sha: str
    created_at: datetime
    pr_number: int | None = None


@dataclass(frozen=True)
class QuarantinedIdentifierEntry:
    """A quarantined snapshot identifier."""

    id: UUID
    identifier: str
    run_type: str
    reason: str
    # Who opened it: a person in the UI, or an agent through MCP. `created_by` is
    # the delegating user either way, so it cannot answer this on its own.
    source: str
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    created_by: UserBasicInfo | None = None
    # Set when the quarantine was created from the run scene (we knew which
    # failing snapshot prompted it). None for quarantines opened from the
    # snapshot history page or pre-dating this column.
    source_run: QuarantineSourceRun | None = None


@dataclass(frozen=True)
class QuarantineInput:
    """Input for quarantining an identifier. run_type comes from URL path."""

    identifier: str
    reason: str
    expires_at: datetime | None = None
    # Optional pointer to the run whose failing snapshot prompted this
    # quarantine. Passed by the run scene so reviewers can jump back to
    # "what was wrong" later. Omitted when quarantining from the snapshot
    # history page where no run is in context.
    source_run_id: UUID | None = None


@dataclass(frozen=True)
class UpdateRepoRequestInput:
    """Request body for updating a repo. repo_id comes from URL."""

    baseline_file_paths: dict[str, str] | None = None
    enable_pr_comments: bool | None = None


@dataclass(frozen=True)
class UpdateRepoInput:
    """Full input for updating a repo (internal use)."""

    repo_id: UUID
    baseline_file_paths: dict[str, str] | None = None
    enable_pr_comments: bool | None = None


@dataclass(frozen=True)
class SnapshotHistoryEntry:
    """A single entry in a snapshot's change history across runs."""

    run_id: UUID
    snapshot_id: UUID
    result: str
    branch: str
    commit_sha: str
    created_at: datetime
    pr_number: int | None = None
    diff_percentage: float | None = None
    review_state: str = ""
    current_artifact: Artifact | None = None
    # Diff classification — see ChangeKind enum. Lets the history view
    # render categorical chips ('Perceptible change' / 'Size changed') instead
    # of conflating SSIM dissimilarity with pixel diff %. `cluster_summary`
    # deliberately omitted here — bbox overlays don't apply to a
    # list-of-history-rows view; load the full snapshot for those.
    ssim_score: float | None = None
    change_kind: str = ""
    size_mismatch: bool = False


@dataclass(frozen=True)
class Repo:
    """A visual review repo."""

    id: UUID
    team_id: int
    repo_external_id: int
    repo_full_name: str
    baseline_file_paths: dict[str, str]
    enable_pr_comments: bool
    created_at: datetime


# Hard cap on entries returned by the baselines overview endpoint. Above this,
# truncate (newest by run completion) and surface `truncated: True` so the UI
# can flag it. The whole flow is sized for this — the FE filters/sorts client-
# side and ships ~600 KB gzipped at the cap.
BASELINE_OVERVIEW_MAX_ENTRIES = 5000

# Number of most-recent default-branch completed runs that feed the
# `recent_drift_avg` smoothing window. Bounded by run count rather than time
# so a busy repo doesn't drag in proportionally more rows. ~10 runs is enough
# to wash out a single jittery render while staying responsive on real changes.
BASELINE_DRIFT_RECENT_RUN_COUNT = 10


@dataclass(frozen=True)
class BaselineQuarantineSummary:
    """Compact view of the active quarantine attached to a baseline entry.

    Embedded on `BaselineEntry` so the overview grid can render rich details
    (reason, expiry, who, source run) without a per-card fetch.
    """

    id: UUID
    reason: str
    source: str
    expires_at: datetime | None
    created_at: datetime
    created_by: UserBasicInfo | None = None
    source_run: QuarantineSourceRun | None = None


@dataclass(frozen=True)
class BaselineEntry:
    """The current baseline state of a single snapshot identifier in a repo.

    Anchored on the latest non-superseded run on the default branch (master/main)
    for each `run_type` — i.e. "what is the baseline image we'd compare against
    right now". One row per `(run_type, identifier)`.
    """

    identifier: str
    run_type: str
    browser: str | None
    thumbnail_hash: str | None
    width: int | None
    height: int | None
    tolerate_count_30d: int
    tolerate_count_90d: int
    is_quarantined: bool
    last_run_at: datetime
    # Lifetime count of YAML baseline flips on master/main for this identifier.
    # Counts RunSnapshots with `result IN (CHANGED, REMOVED)` — the rows that
    # represent an actual baseline-update event (subsequent runs see UNCHANGED
    # against the new baseline). Drives the "most-changed" sort.
    baseline_change_count: int
    # AVG(diff_percentage) over the last N completed default-branch runs (see
    # `BASELINE_DRIFT_RECENT_RUN_COUNT`), filtered to runs that produced a
    # non-zero diff. Drives the drift-severity sort. None when no signal in
    # the window.
    recent_drift_avg: float | None
    # Populated when `is_quarantined` is true. Lets the overview grid show
    # reason / expiry / who / source-run inline instead of just a yellow icon.
    quarantine: BaselineQuarantineSummary | None = None


@dataclass(frozen=True)
class BaselineTotals:
    """Aggregate counts across the **full** baseline universe.

    Computed independently of pagination so the stat row stays correct when
    `entries` is truncated. The FE uses these for unfiltered counts and falls
    back to recomputing over `entries` once a filter is active.
    """

    all_snapshots: int
    recently_tolerated: int
    frequently_tolerated: int
    currently_quarantined: int
    by_run_type: dict[str, int]


@dataclass(frozen=True)
class BaselineOverview:
    """Result of the baselines overview endpoint."""

    entries: list[BaselineEntry]
    totals: BaselineTotals
    truncated: bool
    generated_at: datetime


# How far back the page reads. Sets the width of the per-day activity strip and
# the span `headroom` looks over, where more days mean better evidence of the
# worst case a snapshot can produce.
FLAKINESS_WINDOW_DAYS = 30

# How far back the rates count, inside that window. Shorter on purpose, and
# shorter than the strip: the rates decide whether a snapshot is failing *now*,
# and a quarantine over one that stopped failing three weeks ago has to become
# liftable rather than keep reporting the failures it used to have.
#
# The default branch lands a run every few minutes on an active repo, so a week
# is hundreds of runs. That is far more than a rate needs, and widening it only
# blunts the signal.
FLAKINESS_RATE_DAYS = 7

# Hard-failure rate at or above which a snapshot is broken rather than flaky.
# The two need different actions: a flaky snapshot wants a quarantine or a
# stabilized story, a broken one wants its baseline fixed, and quarantining it
# only hides that.
FLAKINESS_BROKEN_RATE = 0.9

# Below this many runs in the window, a rate is not worth reporting as one:
# one failure out of two runs is 50% and means nothing. Rows under it still
# list, they just cannot reach `broken`.
FLAKINESS_MIN_WINDOW_RUNS = 5

# Fraction of the pixel threshold a snapshot must keep free to count as having
# headroom. Below it, the snapshot passes only because its diff has stayed on
# the safe side of a line it is already touching, and the next unrelated
# rendering change pushes it over.
FLAKINESS_MIN_HEADROOM = 0.2

# A quarantine this close to running out needs a human to extend it or let it
# lapse, so it counts toward `needs_decision`.
FLAKINESS_EXPIRY_SOON_DAYS = 7

# Safety cap on rows returned by the flakiness endpoint. The population is
# already narrow (only identifiers carrying variants or a quarantine), so this
# is a backstop against a repo whose diff threshold is misconfigured and
# tolerates everything, not an expected limit.
FLAKINESS_MAX_ENTRIES = 2000


@dataclass(frozen=True)
class FlakinessEntry:
    """How unstable one snapshot identity is, and what is being done about it.

    One row per `(run_type, identifier)`. Only identifiers that carry at least
    one live variant against their current baseline, or an active quarantine,
    get an entry — everything else has nothing to report.
    """

    identifier: str
    run_type: str
    browser: str | None
    thumbnail_hash: str | None
    width: int | None
    height: int | None
    # Distinct alternate hashes the classifier can still match for this
    # snapshot's current baseline. Reads as "how many different images this
    # snapshot is currently allowed to produce".
    variant_count: int
    # Default-branch runs in the window that rendered this snapshot differently
    # from its baseline, split by what that cost. `hard` failed the gate.
    # `soft` was absorbed by a toleration and blocked nobody.
    hard_count: int
    soft_count: int
    # Completed default-branch runs of this run type in the window. The rate
    # denominator, reported so a reader can tell 2 failures out of 3 runs from
    # 2 out of 300.
    window_runs: int
    # `hard_count` and `soft_count` over `window_runs`, clamped to 1.0. The
    # denominator counts every run of this run type, so a snapshot that only
    # started rendering partway through the window reads lower than it is.
    hard_rate: float
    soft_rate: float
    # Last default-branch run in the window that rendered a difference of
    # either kind. None when every run in the window matched the baseline.
    last_flaked_at: datetime | None
    # Mean pixel-diff fraction across the live variants. Separates sub-pixel
    # noise from a small but real rendering change.
    avg_diff_percentage: float | None
    # Worst pixel diff any absorbed run in the window produced, and what
    # fraction of the pixel threshold that leaves free. A snapshot always
    # tolerated at 0.01% is safe; one always tolerated just under the
    # threshold passes on luck, and the next unrelated change turns it red.
    # None when nothing was absorbed in the window.
    worst_soft_diff_percentage: float | None
    headroom: float | None
    # Days since the first default-branch run that compared against the
    # current baseline, which is when that baseline took effect.
    baseline_age_days: int | None
    # Hard and soft runs per day over the window, oldest first. Always
    # `FLAKINESS_WINDOW_DAYS` long so the frontend can render a fixed axis.
    daily_hard_counts: list[int]
    daily_soft_counts: list[int]
    # Index into the daily series where the baseline moved. None when it moved
    # before the window opened, which is the common case.
    baseline_moved_day_index: int | None
    # One of `FlakinessState`. Named with a prefix because a field called
    # `state` collides with other products' enums in the OpenAPI schema.
    flakiness_state: str
    is_quarantined: bool
    # True when an active quarantine has run out, is about to, or covers a
    # snapshot that has stopped failing. All three mean a human has to choose
    # between extending it and lifting it.
    needs_decision: bool
    quarantine: BaselineQuarantineSummary | None = None


@dataclass(frozen=True)
class FlakinessTotals:
    """Counts across the full population, independent of any client-side filter."""

    # Identifiers with an entry in `entries`.
    listed: int
    # Identifiers with a current baseline, listed or not. The denominator that
    # tells a reader how much of the repo is quiet.
    tracked: int
    broken: int
    unstable: int
    at_risk: int
    noisy: int
    # Listed, but nothing failing or absorbed inside the rate span. A row
    # reaches this state by carrying live variants, or history further back in
    # the read window, so it is reported rather than silently unreachable.
    clean: int
    quarantined: int
    needs_decision: int
    by_run_type: dict[str, int]


@dataclass(frozen=True)
class FlakinessOverview:
    """Result of the flakiness overview endpoint."""

    entries: list[FlakinessEntry]
    totals: FlakinessTotals
    truncated: bool
    generated_at: datetime
