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


class DocKind(StrEnum):
    """A page the space writes, or the one doc that is the space's own context notes."""

    PAGE = "page"
    CONTEXT = "context"


class DocTemplate(StrEnum):
    """What a new doc starts with. Templates are plain starting content, not a live type."""

    BLANK = "blank"
    NOTES = "notes"


class CollabSubmitStatus(StrEnum):
    ACCEPTED = "accepted"
    CONFLICT = "conflict"
    STALE = "stale"


class DiscussionKind(StrEnum):
    """What a thread hangs off: a phrase in the text, or a data point the page asked for."""

    TEXT = "text"
    DATA = "data"
    # A section the agent keeps checking on a schedule; each report is a post.
    WATCH = "watch"


class PostAuthorKind(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


class AgentDelivery(StrEnum):
    """What happened to a post that was meant for the agent."""

    NOT_REQUESTED = "not_requested"
    SENT = "sent"
    NO_RUN = "no_run"
    FAILED = "failed"


class DataPointStatus(StrEnum):
    OK = "ok"
    NONE = "none"


class DataShape(StrEnum):
    """What a data point's query gives back, which decides how the page draws it."""

    NUMBER = "number"
    SERIES = "series"
    TABLE = "table"
