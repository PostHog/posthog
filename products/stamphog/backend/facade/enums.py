"""
Exported enums for stamphog.

If an enum appears in a contract dataclass field, it belongs here.
Internal-only constants (DB magic values, feature flags) stay in
the implementation (logic/, models.py).
"""

from enum import StrEnum


class ReviewRunStatus(StrEnum):
    QUEUED = "queued"
    GATED = "gated"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class ReviewVerdict(StrEnum):
    NONE = "none"
    APPROVED = "approved"
    REFUSED = "refused"
    ESCALATE = "escalate"
    WAIT = "wait"
    ERROR = "error"
