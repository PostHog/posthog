"""Order candidates into one list and choose what the text and the left bar show. Pure functions."""

from posthog.dataclasses import frozen

from ..facade.enums import ItemGroup
from .candidates import Candidate

# Breaks ties between items of the same urgency: a report before a dashboard before the rest.
GROUP_ORDER = {ItemGroup.REPORT: 0, ItemGroup.DASHBOARD: 1, ItemGroup.OTHER: 2}
TEXT_SIZE = 5
BAR_SIZE = 10


@frozen
class RankedItem:
    candidate: Candidate
    rank: int
    in_text: bool
    top: bool


def rank_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """One list across every source: most urgent first, then by group, then by the source's own order."""
    ordered = sorted(candidates, key=lambda c: (c.urgency, GROUP_ORDER[c.group], c.sort_key))
    seen: set[str] = set()
    unique = []
    for candidate in ordered:
        if candidate.key not in seen:
            seen.add(candidate.key)
            unique.append(candidate)
    return unique


def select(ranked: list[Candidate]) -> list[RankedItem]:
    """The left bar items in rank order, marking the text items and the highlighted top item.

    The text takes the 5 most urgent items whatever their kind, and the first of them is the one
    the text highlights. The left bar shows those plus the next best items, up to 10, so an item in
    the text is always in the left bar too.
    """
    bar = ranked[:BAR_SIZE]
    chosen = {candidate.key for candidate in bar[:TEXT_SIZE]}
    top_key = bar[0].key if bar else None
    return [
        RankedItem(candidate=c, rank=rank, in_text=c.key in chosen, top=c.key == top_key)
        for rank, c in enumerate(bar, start=1)
    ]
