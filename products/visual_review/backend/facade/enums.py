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


class ChangeKind(StrEnum):
    """What kind of change a CHANGED snapshot represents.

    Set when a snapshot's `result` is CHANGED. The two-tier classifier
    distinguishes a pixel-level diff (lots of pixels differ) from a
    structural/perceptual change caught by SSIM (few pixels but a measurable
    perceptual difference). Empty for snapshots that haven't been diffed yet (legacy data).

    Size mismatch is *not* a kind here — a snapshot can have a different
    viewport AND a content change. The flag lives in `diff_metadata`
    instead so it composes with whichever kind the classifier picks.
    """

    PIXEL = "pixel"  # Pixel diff above threshold — a chunk of pixels visibly changed
    STRUCTURAL = "structural"  # SSIM caught a perceptual change; pixel diff was below threshold


class FlakinessState(StrEnum):
    """How unstable a snapshot's rendering is, and what to do about it.

    Derived, not stored. Scored on how often default-branch runs in the window
    rendered the snapshot differently from its baseline, and on how much of the
    diff threshold the absorbed ones leave free. The ladder is ordered by
    urgency, and each rung asks for a different fix.
    """

    BROKEN = "broken"  # Fails nearly every run: the baseline is wrong, not the story
    UNSTABLE = "unstable"  # Fails some runs and not others: the classic flake
    AT_RISK = "at_risk"  # Never fails, but its diff is already touching the threshold
    NOISY = "noisy"  # Renders variants, absorbed with room to spare
    CLEAN = "clean"  # Matched its baseline on every run in the window


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
