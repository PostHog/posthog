"""Order candidates into one list and choose what the text and the left bar show. Pure functions."""

from posthog.dataclasses import frozen

from ..facade.enums import ItemGroup
from .candidates import Candidate

GROUP_ORDER = {ItemGroup.REPORT: 0, ItemGroup.DASHBOARD: 1, ItemGroup.OTHER: 2}
TEXT_CAPS = {ItemGroup.REPORT: 2, ItemGroup.DASHBOARD: 2, ItemGroup.OTHER: 1}
TEXT_SIZE = 5
BAR_SIZE = 10


@frozen
class RankedItem:
    candidate: Candidate
    rank: int
    in_text: bool
    top: bool


def rank_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """One list: groups in order, each group by its own sort keys, duplicates dropped."""
    ordered = sorted(candidates, key=lambda c: (GROUP_ORDER[c.group], c.sort_key))
    seen: set[str] = set()
    unique = []
    for candidate in ordered:
        if candidate.key not in seen:
            seen.add(candidate.key)
            unique.append(candidate)
    return unique


def select(ranked: list[Candidate]) -> list[RankedItem]:
    """The left bar items in rank order, marking the text items and the highlighted top item.

    The text takes 5 items from the whole list with variety (2 reports, 2 dashboards, 1 other),
    and free slots go to the next best items. The left bar shows the text items plus the next
    best items, up to 10, so an item in the text is always in the left bar too.
    """
    chosen: list[str] = []
    used = dict.fromkeys(TEXT_CAPS, 0)
    for candidate in ranked:
        if len(chosen) < TEXT_SIZE and used[candidate.group] < TEXT_CAPS[candidate.group]:
            chosen.append(candidate.key)
            used[candidate.group] += 1
    for candidate in ranked:
        if len(chosen) >= TEXT_SIZE:
            break
        if candidate.key not in chosen:
            chosen.append(candidate.key)
    rank_of = {candidate.key: position for position, candidate in enumerate(ranked, start=1)}
    bar = [c for c in ranked if c.key in chosen]
    bar += [c for c in ranked if c.key not in chosen][: BAR_SIZE - len(bar)]
    bar.sort(key=lambda c: rank_of[c.key])
    top_key = next((c.key for c in bar if c.key in chosen and c.group == ItemGroup.REPORT), None)
    if top_key is None:
        top_key = next((c.key for c in bar if c.key in chosen), None)
    return [RankedItem(candidate=c, rank=rank_of[c.key], in_text=c.key in chosen, top=c.key == top_key) for c in bar]
