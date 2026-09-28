"""Collapse the labeling suite's answers for one (question, recording) cell into a single reference answer.

The consensus keeps the labeling suite's own answer shape, so a scorer reads a reference answer and a
labeler's answer the same way. Question types with no comparable value (free text, ranking,
correction) produce no consensus; the benchmark leaves them out.
"""

import statistics
from collections import Counter
from typing import Any

from pydantic import BaseModel

# A consensus needs at least two independent answers; one labeler is an opinion, not agreement.
MIN_LABELS = 2
# Spans from different labelers belong to the same moment when they overlap at all or sit this close.
SPAN_JOIN_TOLERANCE_MS = 2_000


class Question(BaseModel, frozen=True):
    question_id: str
    version: int
    type: str
    # The labeling suite's question JSON: prompt, options, sub-questions and flags.
    definition: dict[str, Any]


class Span(BaseModel, frozen=True):
    start_ms: int
    end_ms: int


class CellConsensus(BaseModel, frozen=True):
    question_id: str
    question_version: int
    recording_id: str
    answer: dict[str, Any]
    # Share of labelers whose answer matches the consensus; None where answers have no single comparable value.
    agreement: float | None
    label_count: int


def cell_consensus(question: Question, recording_id: str, labels: list[dict[str, Any]]) -> CellConsensus | None:
    if len(labels) < MIN_LABELS:
        return None
    result = _majority_answer(question, labels)
    if result is None:
        return None
    answer, agreement = result
    return CellConsensus(
        question_id=question.question_id,
        question_version=question.version,
        recording_id=recording_id,
        answer={"questionId": question.question_id, "type": question.type, **answer},
        agreement=agreement,
        label_count=len(labels),
    )


def _majority_answer(question: Question, labels: list[dict[str, Any]]) -> tuple[dict[str, Any], float | None] | None:
    definition = question.definition
    if question.type == "binary":
        return _majority_value([label.get("choice") for label in labels], lambda choice: {"choice": choice})
    if question.type == "multiple_choice":
        if definition.get("optionScale"):
            return _median_ratings(labels)
        if definition.get("multiple"):
            return _per_option_majority(definition, labels)
        choices = [_single_choice(label) for label in labels]
        if definition.get("ordinal"):
            return _median_choice(choices)
        return _majority_value(choices, lambda index: {"choiceIndices": [index]})
    if question.type == "itemized":
        return _span_consensus([_itemized_spans(label) for label in labels])
    if question.type == "timeline_marking":
        return _span_consensus([_marker_spans(label) for label in labels])
    return None


def _majority_value(values: list[Any], build: Any) -> tuple[dict[str, Any], float] | None:
    answered = [value for value in values if value is not None]
    if len(answered) < MIN_LABELS:
        return None
    ranked = Counter(answered).most_common()
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    value, count = ranked[0]
    return build(value), count / len(answered)


def _single_choice(label: dict[str, Any]) -> int | None:
    indices = label.get("choiceIndices") or []
    return indices[0] if len(indices) == 1 else None


def _median_choice(choices: list[int | None]) -> tuple[dict[str, Any], float] | None:
    answered = [choice for choice in choices if choice is not None]
    if len(answered) < MIN_LABELS:
        return None
    median = round(statistics.median(answered))
    return {"choiceIndices": [median]}, sum(1 for choice in answered if choice == median) / len(answered)


def _per_option_majority(
    definition: dict[str, Any], labels: list[dict[str, Any]]
) -> tuple[dict[str, Any], float] | None:
    option_count = len(definition.get("options", []))
    chosen = [set(label.get("choiceIndices") or []) for label in labels]
    majority = sorted(index for index in range(option_count) if sum(index in c for c in chosen) * 2 > len(chosen))
    # No option with a majority is disagreement, not a shared answer of "none", unless most chose none.
    if not majority and sum(not c for c in chosen) * 2 <= len(chosen):
        return None
    agreement = sum(1 for c in chosen if c == set(majority)) / len(chosen)
    return {"choiceIndices": majority}, agreement


def _median_ratings(labels: list[dict[str, Any]]) -> tuple[dict[str, Any], None] | None:
    by_option: dict[str, list[int]] = {}
    for label in labels:
        for option_id, rating in (label.get("ratings") or {}).items():
            by_option.setdefault(option_id, []).append(rating)
    ratings = {
        option_id: round(statistics.median(values))
        for option_id, values in by_option.items()
        if len(values) >= MIN_LABELS
    }
    if not ratings:
        return None
    return {"ratings": ratings}, None


def _itemized_spans(label: dict[str, Any]) -> list[Span]:
    spans: list[Span] = []
    for item in label.get("items") or []:
        if item.get("spans"):
            spans.extend(Span(start_ms=s["startMs"], end_ms=s["endMs"]) for s in item["spans"])
        elif item.get("startMs") is not None and item.get("endMs") is not None:
            spans.append(Span(start_ms=item["startMs"], end_ms=item["endMs"]))
    return spans


def _marker_spans(label: dict[str, Any]) -> list[Span]:
    return [Span(start_ms=m["startMs"], end_ms=m["endMs"]) for m in label.get("markers") or []]


def _span_consensus(per_labeler: list[list[Span]]) -> tuple[dict[str, Any], float] | None:
    """Presence by majority, plus the moments at least two labelers marked.

    Each moment is a cluster of overlapping spans from two or more labelers, reported as the median of their
    edges. A moment only one labeler marked is left out: it may be real, but it is not agreed ground truth.
    """
    present = [len(spans) > 0 for spans in per_labeler]
    presence = _majority_value(present, lambda value: {"present": value})
    if presence is None:
        return None
    answer, agreement = presence
    tagged = sorted(
        ((span, labeler) for labeler, spans in enumerate(per_labeler) for span in spans),
        key=lambda pair: pair[0].start_ms,
    )
    clusters: list[list[tuple[Span, int]]] = []
    cluster_end = -1
    for span, labeler in tagged:
        if clusters and span.start_ms <= cluster_end + SPAN_JOIN_TOLERANCE_MS:
            clusters[-1].append((span, labeler))
            cluster_end = max(cluster_end, span.end_ms)
        else:
            clusters.append([(span, labeler)])
            cluster_end = span.end_ms
    moments = [
        {
            "startMs": round(statistics.median(span.start_ms for span, _ in cluster)),
            "endMs": round(statistics.median(span.end_ms for span, _ in cluster)),
            "labelers": len({labeler for _, labeler in cluster}),
        }
        for cluster in clusters
        if len({labeler for _, labeler in cluster}) >= MIN_LABELS
    ]
    return {**answer, "moments": moments if answer["present"] else []}, agreement
