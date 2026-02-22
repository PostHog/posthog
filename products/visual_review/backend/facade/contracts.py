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
    baseline_hashes: dict[str, str] = field(default_factory=dict)
    # Run-level metadata (pr_title, ci_job_url, base_branch, etc.)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CreateRepoInput:
    """Input for creating a repo."""

    name: str


@dataclass(frozen=True)
class ApproveSnapshotInput:
    """A snapshot approval from the UI."""

    identifier: str
    new_hash: str


@dataclass(frozen=True)
class ApproveRunRequestInput:
    """Request body for approving a run. run_id and user_id come from URL and auth."""

    snapshots: list[ApproveSnapshotInput]
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
class Snapshot:
    """A snapshot with its comparison results."""

    id: UUID
    identifier: str
    result: str
    current_artifact: Artifact | None
    baseline_artifact: Artifact | None
    diff_artifact: Artifact | None
    diff_percentage: float | None
    diff_pixel_count: int | None
    # Review state (human decision, separate from computed result)
    review_state: str  # pending, approved, (future: rejected)
    reviewed_at: datetime | None
    approved_hash: str
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
    # Flexible metadata (pr_title, ci_job_url, base_branch, etc.)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class UpdateRepoRequestInput:
    """Request body for updating a repo. repo_id comes from URL."""

    name: str | None = None
    repo_full_name: str | None = None
    baseline_file_paths: dict[str, str] | None = None


@dataclass(frozen=True)
class UpdateRepoInput:
    """Full input for updating a repo (internal use)."""

    repo_id: UUID
    name: str | None = None
    repo_full_name: str | None = None
    baseline_file_paths: dict[str, str] | None = None


@dataclass(frozen=True)
class Repo:
    """A visual review repo."""

    id: UUID
    team_id: int
    name: str
    repo_full_name: str
    baseline_file_paths: dict[str, str]
    created_at: datetime
