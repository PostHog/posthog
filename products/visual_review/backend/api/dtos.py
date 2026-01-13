"""
DTOs for visual_review API.

Stable, framework-free dataclasses that serve as internal contracts.
No Django imports. Immutable (frozen=True).
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


@dataclass(frozen=True)
class CreateRunInput:
    """Input for creating a new visual review run."""

    project_id: UUID
    run_type: str
    commit_sha: str
    branch: str
    snapshots: list[SnapshotManifestItem]
    pr_number: int | None = None
    baseline_hashes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RegisterArtifactInput:
    """Input for registering an artifact after upload."""

    project_id: UUID
    content_hash: str
    storage_path: str
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None


@dataclass(frozen=True)
class ApproveSnapshotInput:
    """A snapshot approval from the UI."""

    identifier: str
    new_hash: str


@dataclass(frozen=True)
class ApproveRunInput:
    """Input for approving visual changes."""

    run_id: UUID
    user_id: int
    snapshots: list[ApproveSnapshotInput]


# --- Output DTOs ---


@dataclass(frozen=True)
class CreateRunResult:
    """Result of creating a run."""

    run_id: UUID
    missing_hashes: list[str]


@dataclass(frozen=True)
class UploadUrl:
    """Presigned URL for artifact upload."""

    url: str
    fields: dict[str, str]


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
    project_id: UUID
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


@dataclass(frozen=True)
class Project:
    """A visual review project."""

    id: UUID
    team_id: int
    name: str
    created_at: datetime
