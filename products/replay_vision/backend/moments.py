from typing import Any

from pydantic import BaseModel, Field

# Clip bounds around a focus event; capped so a moment stays a short clip, not a session re-run.
MIN_MOMENT_WINDOW_SECONDS = 5
MAX_MOMENT_WINDOW_SECONDS = 300

DEFAULT_BEFORE_SECONDS = 60
DEFAULT_AFTER_SECONDS = 60

# Bounds the OR fan-out in the candidate query and keeps the config UI sane.
MAX_MOMENT_EVENTS = 10


class MomentEvent(BaseModel, frozen=True):
    """One focus event: occurrences of this event anchor the moments a scanner watches."""

    event: str = Field(min_length=1, max_length=400, description="Event name whose occurrences anchor moments.")
    # Loose dicts on purpose — these are spliced into `RecordingsQuery.events`, which is `list[dict]`;
    # property-filter shape is validated where the query compiles, same as the scanner's main filters.
    properties: list[dict[str, Any]] = Field(
        default_factory=list, description="Property filters the occurrence must also match."
    )


class MomentsConfig(BaseModel, frozen=True):
    """Scope configuration for moments-scoped scanners: which events to focus on, and the clip bounds around them.

    Persisted as `ReplayScanner.moments_config` and frozen into `ScannerSnapshot`, so shape changes
    must stay loadable for old rows (new fields need defaults).
    """

    events: list[MomentEvent] = Field(
        min_length=1,
        max_length=MAX_MOMENT_EVENTS,
        description="Focus events; a moment is scanned around each occurrence of any of them.",
    )
    before_seconds: int = Field(
        default=DEFAULT_BEFORE_SECONDS, ge=MIN_MOMENT_WINDOW_SECONDS, le=MAX_MOMENT_WINDOW_SECONDS
    )
    after_seconds: int = Field(
        default=DEFAULT_AFTER_SECONDS, ge=MIN_MOMENT_WINDOW_SECONDS, le=MAX_MOMENT_WINDOW_SECONDS
    )
