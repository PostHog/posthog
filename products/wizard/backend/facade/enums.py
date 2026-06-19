"""
Exported enums for wizard.

If an enum appears in a contract dataclass field, it belongs here.
Internal-only constants (DB magic values, feature flags) stay in
the implementation (logic.py, models.py).
"""

from enum import StrEnum


class RunPhase(StrEnum):
    """Phase of a run."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


class TaskStatus(StrEnum):
    """Status of a task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"

    # These are not currently used, but we want to reserve them for future use.
    FAILED = "failed"
    CANCELED = "canceled"
