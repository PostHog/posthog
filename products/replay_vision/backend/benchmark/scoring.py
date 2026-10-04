"""Score one comparable answer against another, and one answer against every labeler's.

A similarity is 1.0 for full agreement and 0.0 for none. It is symmetric, so the same function scores
Replay Vision against a labeler and one labeler against another. The labelers' agreement with each other
is the ceiling Replay Vision's agreement with them can be read against.
"""

import statistics
from typing import Any

from products.replay_vision.backend.benchmark.labels import Question

# Two moments match when they overlap or sit this close. A Replay Vision citation is a single point in time.
MOMENT_MATCH_TOLERANCE_MS = 2_000


def similarity(question: Question, answer: dict[str, Any], reference: dict[str, Any]) -> float | None:
    """How far two comparable answers agree, or None when they share nothing to compare."""
    kind = question.kind
    if kind in ("binary", "choice"):
        key = "choice" if kind == "binary" else "choiceIndices"
        return float(answer[key] == reference[key])
    if kind == "ordinal":
        steps = max(len(question.options) - 1, 1)
        return 1.0 - abs(answer["choiceIndices"][0] - reference["choiceIndices"][0]) / steps
    if kind == "multi":
        chosen, expected = set(answer["choiceIndices"]), set(reference["choiceIndices"])
        return len(chosen & expected) / len(chosen | expected) if chosen | expected else 1.0
    if kind == "ratings":
        return _ratings_similarity(question.scale_max, answer["ratings"], reference["ratings"])
    if kind == "spans":
        return _spans_similarity(answer, reference)
    return None


def label_agreement(question: Question, answer: dict[str, Any], labels: list[dict[str, Any]]) -> float | None:
    """Mean similarity of an answer to each labeler's answer."""
    scores = [score for label in labels if (score := similarity(question, answer, label)) is not None]
    return statistics.fmean(scores) if scores else None


def labeler_agreement(question: Question, labels: list[dict[str, Any]]) -> float | None:
    """Each labeler scored against the others, averaged: None with fewer than two labelers."""
    scores = [
        score
        for index, label in enumerate(labels)
        if (score := label_agreement(question, label, labels[:index] + labels[index + 1 :])) is not None
    ]
    return statistics.fmean(scores) if len(labels) > 1 and scores else None


def _ratings_similarity(scale_max: int, answer: dict[str, int], reference: dict[str, int]) -> float | None:
    shared = answer.keys() & reference.keys()
    if not shared:
        return None
    steps = max(scale_max - 1, 1)
    return statistics.fmean(1.0 - abs(answer[option] - reference[option]) / steps for option in shared)


def _spans_similarity(answer: dict[str, Any], reference: dict[str, Any]) -> float:
    """Presence first, then an F1 over moments when both sides placed any."""
    if answer["present"] != reference["present"]:
        return 0.0
    placed, expected = answer["moments"], reference["moments"]
    if not placed or not expected:
        return 1.0
    precision = sum(any(_overlaps(a, e) for e in expected) for a in placed) / len(placed)
    recall = sum(any(_overlaps(a, e) for a in placed) for e in expected) / len(expected)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _overlaps(a: dict[str, int], b: dict[str, int]) -> bool:
    return (
        a["startMs"] <= b["endMs"] + MOMENT_MATCH_TOLERANCE_MS
        and b["startMs"] <= a["endMs"] + MOMENT_MATCH_TOLERANCE_MS
    )
