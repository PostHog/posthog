"""
Exported enums for docs.

If an enum appears in a contract dataclass field, it belongs here.
Internal-only constants (DB magic values, feature flags) stay in
the implementation (logic/, models.py).
"""

from enum import StrEnum


class DocStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DONE = "done"


class DocTemplate(StrEnum):
    """What a new doc starts with. Templates are plain starting content, not a live type."""

    BLANK = "blank"
    NOTES = "notes"


class CollabSubmitStatus(StrEnum):
    ACCEPTED = "accepted"
    CONFLICT = "conflict"
    STALE = "stale"
