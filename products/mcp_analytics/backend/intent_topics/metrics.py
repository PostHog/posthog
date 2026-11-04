"""Pure metrics over per-topic call counts: focus (consolidation) and drift between two periods."""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

FocusBand = Literal["consolidated", "mixed", "spread"]

CONSOLIDATED_MIN_SCORE = 0.7
MIXED_MIN_SCORE = 0.4


def focus_score(topic_counts: Mapping[str, int]) -> float:
    """1 - normalised Shannon entropy of the topic distribution.

    1.0 means every call lands in one topic; 0.0 means calls spread evenly over all topics.
    """
    counts = [count for count in topic_counts.values() if count > 0]
    total = sum(counts)
    if total == 0:
        return 0.0
    if len(counts) == 1:
        return 1.0
    entropy = -sum((count / total) * math.log(count / total) for count in counts)
    return 1.0 - entropy / math.log(len(counts))


def focus_band(score: float) -> FocusBand:
    if score >= CONSOLIDATED_MIN_SCORE:
        return "consolidated"
    if score >= MIXED_MIN_SCORE:
        return "mixed"
    return "spread"


@dataclass(frozen=True)
class Drift:
    new: list[str] = field(default_factory=list)
    growing: list[str] = field(default_factory=list)
    shrinking: list[str] = field(default_factory=list)
    gone: list[str] = field(default_factory=list)


def _shares(counts: Mapping[str, int]) -> dict[str, float]:
    total = sum(count for count in counts.values() if count > 0)
    if total == 0:
        return {}
    return {topic: count / total for topic, count in counts.items() if count > 0}


def drift(
    current: Mapping[str, int],
    previous: Mapping[str, int],
    *,
    min_calls: int = 5,
    ratio: float = 1.5,
) -> Drift:
    """Classify topics by how their share moved between two periods.

    A topic needs at least ``min_calls`` in the period that makes the claim: ``new`` and ``growing``
    need them now, ``shrinking`` and ``gone`` needed them before. Growing and shrinking compare
    shares, so a flat topic in a growing server does not read as shrinking. Lists are ordered by
    the current period's calls, then the previous period's, descending.
    """
    current_shares = _shares(current)
    previous_shares = _shares(previous)
    new: list[str] = []
    growing: list[str] = []
    shrinking: list[str] = []
    gone: list[str] = []

    for topic, share in current_shares.items():
        if current[topic] < min_calls:
            continue
        before = previous_shares.get(topic)
        if before is None:
            new.append(topic)
        elif share >= before * ratio:
            growing.append(topic)
    for topic, share in previous_shares.items():
        if previous[topic] < min_calls:
            continue
        now = current_shares.get(topic)
        if now is None:
            gone.append(topic)
        elif share >= now * ratio:
            shrinking.append(topic)

    def order(topics: list[str]) -> list[str]:
        return sorted(topics, key=lambda topic: (-current.get(topic, 0), -previous.get(topic, 0), topic))

    return Drift(new=order(new), growing=order(growing), shrinking=order(shrinking), gone=order(gone))
