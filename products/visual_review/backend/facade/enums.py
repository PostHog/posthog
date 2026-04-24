"""Exported enums and constants for visual_review."""

from enum import StrEnum


class RunStatus(StrEnum):
    """Status of a visual review run."""

    PENDING = "pending"  # Waiting for artifacts to be uploaded
    PROCESSING = "processing"  # Diff computation in progress
    COMPLETED = "completed"  # All diffs computed, results ready
    FAILED = "failed"  # Processing failed


class RunType(StrEnum):
    """Well-known run type constants. Not exhaustive — users can use any string."""

    STORYBOOK = "storybook"
    PLAYWRIGHT = "playwright"
    CYPRESS = "cypress"
    OTHER = "other"


class SnapshotResult(StrEnum):
    """Result of comparing a snapshot against baseline."""

    UNCHANGED = "unchanged"  # Matches baseline
    CHANGED = "changed"  # Differs from baseline
    NEW = "new"  # No baseline exists
    REMOVED = "removed"  # Baseline exists but snapshot missing


class RunPurpose(StrEnum):
    """Why this run was submitted."""

    REVIEW = "review"  # Expects approval (human or auto) before merge
    OBSERVE = "observe"  # Tracking only — not approvable


class ReviewDecision(StrEnum):
    """Run-level review outcome."""

    PENDING = "pending"
    HUMAN_APPROVED = "human_approved"
    AUTO_APPROVED = "auto_approved"
    AGENT_APPROVED = "agent_approved"
    REJECTED = "rejected"  # Passive annotation — no system effect in MVP


class ReviewState(StrEnum):
    """
    Human review state for a snapshot.

    Separate from SnapshotResult which is the computed diff status.
    ReviewState tracks the human decision and can change between runs.
    """

    PENDING = "pending"  # Not yet reviewed
    APPROVED = "approved"  # Accepted the change — updates baseline
    TOLERATED = "tolerated"  # Acknowledged as rendering noise — does not update baseline
    REJECTED = "rejected"  # Explicitly rejected


class ClassificationReason(StrEnum):
    """Why a snapshot was classified as UNCHANGED."""

    EXACT = "exact"  # Hash matches baseline
    TOLERATED_HASH = "tolerated_hash"  # Matched a known tolerated alternate
    BELOW_THRESHOLD = "below_threshold"  # Diffed this run, below pixel/SSIM threshold


class ActorType(StrEnum):
    """Who performed an action — human user, AI agent, or automated system."""

    HUMAN = "human"
    AGENT = "agent"
    AUTO = "auto"


class ToleratedReason(StrEnum):
    """Why a hash was tolerated."""

    AUTO_THRESHOLD = "auto_threshold"  # Below pixel/SSIM diff threshold
    HUMAN = "human"  # Manually marked by a reviewer
    AGENT = "agent"  # Tolerated by an AI agent
