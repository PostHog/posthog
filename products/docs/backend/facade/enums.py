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
    # A hypothesis the page keeps watching: evidence checks and a scout, with a verdict.
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


class WatchStatus(StrEnum):
    """Whether a watch still runs. Paused waits for the page to reopen; stopped is final."""

    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"


class WatchVerdict(StrEnum):
    """Where the hypothesis stands. Pending until the brief lands; stale when a check could not run."""

    PENDING = "pending"
    HOLDING = "holding"
    MOVED = "moved"
    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    STALE = "stale"


class WatchStopReason(StrEnum):
    SECTION_REMOVED = "section_removed"
    PAGE_DONE = "page_done"
    PAGE_DELETED = "page_deleted"
    HANDLED = "handled"
    PERSON = "person"
    VERDICT = "verdict"


class WatchAction(StrEnum):
    """What a person can do to a watch from its thread."""

    CHECK = "check"
    STOP = "stop"
    RESUME = "resume"
    CLOSE = "close"
    # Stands the scout up when the brief arrived without a person in the room.
    ARM = "arm"


class WatchActor(StrEnum):
    """Who set a verdict."""

    AGENT = "agent"
    PERSON = "person"
    PAGE = "page"


class WatchEvent(StrEnum):
    """What a post the watch wrote stands for, so a timeline reads it without parsing words."""

    BRIEF = "brief"
    CHECK = "check"
    MOVED = "moved"
    STALE = "stale"
    REPORT = "report"
    VERDICT = "verdict"
    SCOUT = "scout"
    STOPPED = "stopped"
    PAUSED = "paused"
    RESUMED = "resumed"
