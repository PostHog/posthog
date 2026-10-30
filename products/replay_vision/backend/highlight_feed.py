"""Ordering for the Highlights feed: a cap on any one scanner's share, spacing between one session's cards, and
the floor of filler rows a quiet window returns."""

import math
from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen

# Filler pads a quiet feed to this many cards, so a window with nothing wrong still shows the newest clips.
HIGHLIGHT_FEED_MIN_ITEMS = 3


@frozen
class HighlightFeedEntry:
    observation_id: UUID
    reason: dict[str, Any]
    # None opts the entry out of session spacing.
    session_id: str | None = None


# One incident can put many near-identical sessions on one scanner, so each scanner holds at most this share of the
# picks, above a floor that keeps a short feed from being over-constrained.
MAX_SCANNER_SHARE = 0.4
_SCANNER_SPREAD_FLOOR = 3


def spread_scanners(ordered: list[tuple[Any, HighlightFeedEntry]]) -> list[HighlightFeedEntry]:
    """Hold each scanner to MAX_SCANNER_SHARE of the picks as it is placed.

    Checked per place rather than over the whole list because the view slices the head: a feed of 5
    obeys the same share as a feed of 50. Overflow trails the picks in score order — reordering
    for breadth is the job here, shortening the feed is not.
    """
    placed: list[HighlightFeedEntry] = []
    deferred: list[HighlightFeedEntry] = []
    counts: dict[Any, int] = {}
    for scanner_id, entry in ordered:
        allowed = max(_SCANNER_SPREAD_FLOOR, math.ceil(MAX_SCANNER_SHARE * (len(placed) + 1)))
        if counts.get(scanner_id, 0) >= allowed:
            deferred.append(entry)
        else:
            counts[scanner_id] = counts.get(scanner_id, 0) + 1
            placed.append(entry)
    return placed + deferred


# Several scanners can pick one recording. Its cards stay this many places apart, so the feed never
# shows the same session twice in a row.
SESSION_SPACING = 5


def space_sessions(entries: list[HighlightFeedEntry]) -> list[HighlightFeedEntry]:
    """Keep each session's cards at least SESSION_SPACING places apart, reordering but never dropping one.

    A held card returns at the first place its session allows, so score order holds otherwise. A feed
    with too few other sessions to space every repeat still ends with every card, in score order.
    """
    placed: list[HighlightFeedEntry] = []
    waiting: list[HighlightFeedEntry] = []
    for entry in entries:
        waiting.append(entry)
        while waiting:
            recent = {placed_entry.session_id for placed_entry in placed[-(SESSION_SPACING - 1) :]} - {None}
            ready = next((held for held in waiting if held.session_id not in recent), None)
            if ready is None:
                break
            waiting.remove(ready)
            placed.append(ready)
    return placed + waiting


def finish_feed(
    picks: list[tuple[float, Any, Any, HighlightFeedEntry]], filler_rows: list[dict[str, Any]]
) -> list[HighlightFeedEntry]:
    """Order `(score, created_at, scanner_id, entry)` picks with the scanner spread and session spacing,
    then pad with `filler_rows` newest and unviewed first, trimmed to the feed's floor."""
    ordered = sorted(picks, key=lambda item: (item[0], item[1]), reverse=True)
    filler: list[tuple[bool, Any, HighlightFeedEntry]] = []
    for row in filler_rows:
        viewed = bool(row.get("feed_viewed"))
        entry = HighlightFeedEntry(observation_id=row["id"], reason={"kind": "recent" if viewed else "unviewed_recent"})
        filler.append((not viewed, row["created_at"], entry))
    filler.sort(key=lambda item: (item[0], item[1]), reverse=True)
    placed = space_sessions(spread_scanners([(scanner_id, entry) for _, _, scanner_id, entry in ordered]))
    return placed + [entry for *_, entry in filler][: max(0, HIGHLIGHT_FEED_MIN_ITEMS - len(placed))]
