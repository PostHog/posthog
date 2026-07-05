import datetime as dt
from typing import Any

from pydantic import BaseModel, Field

# Clip bounds around a focus event; capped so a moment stays a short clip, not a session re-run.
MIN_MOMENT_WINDOW_SECONDS = 5
MAX_MOMENT_WINDOW_SECONDS = 300

DEFAULT_BEFORE_SECONDS = 60
DEFAULT_AFTER_SECONDS = 60

# Bounds the OR fan-out in the candidate query and keeps the config UI sane.
MAX_MOMENT_EVENTS = 10

# Occurrence windows closer than this are merged into one clip even without overlapping.
MOMENT_MERGE_GAP_SECONDS = 5
# Merging stops extending a clip past this; a longer chain of occurrences starts a new moment.
MAX_MOMENT_CLIP_SECONDS = 600
# Caps observations (and quota units) a single session can produce per sweep of one scanner.
MAX_MOMENTS_PER_SESSION = 5


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


class MomentOccurrence(BaseModel, frozen=True):
    """One focus-event occurrence in a session, as returned by the candidate query."""

    uuid: str
    timestamp: dt.datetime
    event: str


class CoalescedMoment(BaseModel, frozen=True):
    """One dispatchable moment: a merged window around one or more focus-event occurrences."""

    # The first occurrence in the merged group; its uuid is the observation's `moment_key`.
    anchor_uuid: str
    anchor_event: str
    anchor_timestamp: dt.datetime
    # Absolute (event-time) bounds of the merged clip, pre-clamping; the scan resolves these against
    # the recording timeline via the anchor's recording-relative offset, not by raw timestamp math.
    window_start: dt.datetime
    window_end: dt.datetime
    occurrence_count: int


def coalesce_moments(
    occurrences: list[MomentOccurrence],
    *,
    before_seconds: int,
    after_seconds: int,
) -> list[CoalescedMoment]:
    """Merge per-occurrence windows into distinct moments; overlapping or near-adjacent windows become one clip.

    Deterministic for a given occurrence set (sorted by timestamp then uuid) — sweep retries must
    regenerate identical anchors or Temporal dedup and the DB constraint stop protecting us.
    Callers cap the result (`MAX_MOMENTS_PER_SESSION`) and account for what they drop.
    """
    if not occurrences:
        return []
    before = dt.timedelta(seconds=before_seconds)
    after = dt.timedelta(seconds=after_seconds)
    gap = dt.timedelta(seconds=MOMENT_MERGE_GAP_SECONDS)
    max_clip = dt.timedelta(seconds=MAX_MOMENT_CLIP_SECONDS)

    ordered = sorted(occurrences, key=lambda o: (o.timestamp, o.uuid))
    moments: list[CoalescedMoment] = []
    anchor = ordered[0]
    count = 1
    group_start = anchor.timestamp - before
    group_end = anchor.timestamp + after

    def flush() -> None:
        moments.append(
            CoalescedMoment(
                anchor_uuid=anchor.uuid,
                anchor_event=anchor.event,
                anchor_timestamp=anchor.timestamp,
                window_start=group_start,
                window_end=group_end,
                occurrence_count=count,
            )
        )

    for occurrence in ordered[1:]:
        window_start = occurrence.timestamp - before
        window_end = occurrence.timestamp + after
        merged_end = max(group_end, window_end)
        if window_start <= group_end + gap and merged_end - group_start <= max_clip:
            count += 1
            group_end = merged_end
        else:
            flush()
            anchor = occurrence
            count = 1
            group_start = window_start
            group_end = window_end
    flush()
    return moments
