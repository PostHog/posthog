"""
Contract types for visual_review.

Stable, framework-free frozen dataclasses that define what this product
exposes to the rest of the codebase. No Django imports.
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

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
    """Request body for approving a run. run_id and user_id come from URL and auth."""

    snapshots: list[ApproveSnapshotInput] = field(default_factory=list)
    approve_all: bool = False
    commit_to_github: bool = True


@dataclass(frozen=True)
class ApproveRunInput:
    """Full input for approving visual changes (internal use)."""

    run_id: UUID
    user_id: int
    snapshots: list[ApproveSnapshotInput]
    commit_to_github: bool = True


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
class Snapshot:
    """A snapshot with its comparison results."""

    id: UUID
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


@dataclass(frozen=True)
class AutoApproveResult:
    """Result of auto-approving a run, including the signed baseline YAML."""

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
class QuarantinedIdentifierEntry:
    """A quarantined snapshot identifier."""

    id: UUID
    identifier: str
    run_type: str
    reason: str
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    created_by: UserBasicInfo | None = None


@dataclass(frozen=True)
class QuarantineInput:
    """Input for quarantining an identifier. run_type comes from URL path."""

    identifier: str
    reason: str
    expires_at: datetime | None = None


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
