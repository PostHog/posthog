"""Ordering for the Highlights feed: a cap on any one scanner's share, spacing between one session's cards, and
the floor of filler rows a quiet window returns."""

import math
from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen

# Reason kinds that say nothing about the session: the fall-through for a row that scored on no source at
# all. They are ordering, not evidence, so the feed carries them only to reach the floor below.
FILLER_REASON_KINDS = frozenset({"unviewed_recent", "recent"})
# How short the feed may get before filler rows pad it. A feed of 3 real findings beats one of 3 findings
# and 17 "new since you last looked", and a feed that empties the moment nothing is wrong reads as broken.
WATCH_FEED_MIN_ITEMS = 3


@frozen
class WatchFeedEntry:
    observation_id: UUID
    reason: dict[str, Any]
    # None opts the entry out of session spacing.
    session_id: str | None = None


def _trim_filler(ranked: list[WatchFeedEntry]) -> list[WatchFeedEntry]:
    """Drop the no-evidence rows once WATCH_FEED_MIN_ITEMS real findings are in the feed.

    `limit` is a ceiling the feed had been filling: a quiet window returned 20 cards of which 17 said
    "New since you last looked", which buries the few that meant something. Findings are kept whatever
    their count; filler only makes up the difference to the floor, so a window with nothing to say
    returns 3 newest clips rather than 20 or an empty state.
    """
    findings = [entry for entry in ranked if entry.reason["kind"] not in FILLER_REASON_KINDS]
    if len(findings) >= WATCH_FEED_MIN_ITEMS:
        return findings
    # Walk rather than concatenate, because a row the reader already opened is docked half a point and can
    # sort below an unviewed filler row — findings are not always a prefix of the list.
    budget = WATCH_FEED_MIN_ITEMS - len(findings)
    kept: list[WatchFeedEntry] = []
    for entry in ranked:
        if entry.reason["kind"] not in FILLER_REASON_KINDS:
            kept.append(entry)
        elif budget > 0:
            kept.append(entry)
            budget -= 1
    return kept


# One incident can put many near-identical sessions on one scanner, so each scanner holds at most this share of the
# picks, above a floor that keeps a short feed from being over-constrained.
MAX_SCANNER_SHARE = 0.4
_SCANNER_SPREAD_FLOOR = 3


def spread_scanners(ordered: list[tuple[Any, WatchFeedEntry]]) -> list[WatchFeedEntry]:
    """Hold each scanner to MAX_SCANNER_SHARE of the evidence tier as it is placed.

    Checked per place rather than over the whole list because the view slices the head: a feed of 5
    obeys the same share as a feed of 50. Overflow trails the tier in score order — reordering
    for breadth is the job here, shortening the feed is not.
    """
    placed: list[WatchFeedEntry] = []
    deferred: list[WatchFeedEntry] = []
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


def space_sessions(entries: list[WatchFeedEntry]) -> list[WatchFeedEntry]:
    """Keep each session's cards at least SESSION_SPACING places apart, reordering but never dropping one.

    A held card returns at the first place its session allows, so score order holds otherwise. A feed
    with too few other sessions to space every repeat still ends with every card, in score order.
    """
    placed: list[WatchFeedEntry] = []
    waiting: list[WatchFeedEntry] = []
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
    picks: list[tuple[float, Any, Any, WatchFeedEntry]], filler_rows: list[dict[str, Any]]
) -> list[WatchFeedEntry]:
    """Order `(score, created_at, scanner_id, entry)` picks with the scanner spread and session spacing,
    then pad with `filler_rows` newest and unviewed first, trimmed to the feed's floor."""
    ordered = sorted(picks, key=lambda item: (item[0], item[1]), reverse=True)
    filler: list[tuple[bool, Any, WatchFeedEntry]] = []
    for row in filler_rows:
        viewed = bool(row.get("feed_viewed"))
        entry = WatchFeedEntry(observation_id=row["id"], reason={"kind": "recent" if viewed else "unviewed_recent"})
        filler.append((not viewed, row["created_at"], entry))
    filler.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return _trim_filler(
        space_sessions(spread_scanners([(scanner_id, entry) for _, _, scanner_id, entry in ordered]))
        + [entry for *_, entry in filler]
    )
