"""Domain types, enums, and constants for visual_review."""

from enum import StrEnum


class RunStatus(StrEnum):
    """Status of a visual review run."""

    PENDING = "pending"  # Waiting for artifacts to be uploaded
    PROCESSING = "processing"  # Diff computation in progress
    COMPLETED = "completed"  # All diffs computed, results ready
    FAILED = "failed"  # Processing failed


class RunType(StrEnum):
    """Type of visual test run."""

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
