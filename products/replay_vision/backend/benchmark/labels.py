"""Reduce each labeler's answer for one (question, recording) cell to a value it can be compared by.

The benchmark scores Replay Vision against every labeler's answer rather than against a consensus, so each
answer is kept on its own. A comparable answer has the same shape whether a labeler or Replay Vision gave
it. Question types with no comparable value (free text, ranking, correction) are left out.
"""

from typing import Any, Literal

from pydantic import BaseModel

AnswerKind = Literal["binary", "choice", "ordinal", "multi", "ratings", "spans"]


class Question(BaseModel, frozen=True):
    question_id: str
    version: int
    type: str
    # The labeling suite's question JSON: prompt, options, sub-questions and flags.
    definition: dict[str, Any]

    @property
    def kind(self) -> AnswerKind | None:
        if self.type == "binary":
            return "binary"
        if self.type == "multiple_choice":
            if self.definition.get("optionScale"):
                return "ratings"
            if self.definition.get("multiple"):
                return "multi"
            return "ordinal" if self.definition.get("ordinal") else "choice"
        if self.type in ("itemized", "timeline_marking"):
            return "spans"
        return None

    @property
    def options(self) -> list[dict[str, Any]]:
        return list(self.definition.get("options") or [])

    @property
    def scale_max(self) -> int:
        return int((self.definition.get("optionScale") or {}).get("max", 0))


class Cell(BaseModel, frozen=True):
    question_id: str
    question_version: int
    recording_id: str
    # One comparable answer per labeler, in the order the labeling suite returned them.
    answers: list[dict[str, Any]]


def labeled_cell(question: Question, recording_id: str, labels: list[dict[str, Any]]) -> Cell | None:
    answers = [answer for label in labels if (answer := comparable_answer(question, label)) is not None]
    if not answers:
        return None
    return Cell(
        question_id=question.question_id,
        question_version=question.version,
        recording_id=recording_id,
        answers=answers,
    )


def comparable_answer(question: Question, label: dict[str, Any]) -> dict[str, Any] | None:
    """The label's comparable value, or None when it holds none: a malformed answer is dropped, not fatal."""
    kind = question.kind
    if kind == "binary":
        choice = label.get("choice")
        return {"choice": choice} if isinstance(choice, bool) else None
    if kind in ("choice", "ordinal"):
        indices = _choice_indices(question, label)
        return {"choiceIndices": indices} if indices is not None and len(indices) == 1 else None
    if kind == "multi":
        indices = _choice_indices(question, label)
        return {"choiceIndices": indices} if indices is not None else None
    if kind == "ratings":
        ratings = {
            option_id: rating
            for option_id, rating in (label.get("ratings") or {}).items()
            # An off-scale or non-integer rating is no answer for that option, the way a span missing an edge is.
            if _is_int(rating) and 1 <= rating <= question.scale_max
        }
        return {"ratings": ratings} if ratings else None
    if kind == "spans":
        spans = _marker_spans(label) if question.type == "timeline_marking" else _itemized_spans(label)
        return {"present": bool(spans), "moments": spans}
    return None


def _is_int(value: Any) -> bool:
    # `type(...) is int` rather than isinstance, which would pass True and False as numbers.
    return type(value) is int


def _choice_indices(question: Question, label: dict[str, Any]) -> list[int] | None:
    indices = label.get("choiceIndices")
    if not isinstance(indices, list) or not all(_is_int(i) and 0 <= i < len(question.options) for i in indices):
        return None
    return sorted(set(indices))


def _span(edges: Any) -> list[dict[str, int]]:
    """A span with both edges, or none: an answer missing one is dropped rather than failing the snapshot."""
    if not isinstance(edges, dict):
        return []
    start, end = edges.get("startMs"), edges.get("endMs")
    return [{"startMs": start, "endMs": end}] if type(start) is int and type(end) is int else []


def _itemized_spans(label: dict[str, Any]) -> list[dict[str, int]]:
    spans: list[dict[str, int]] = []
    for item in label.get("items") or []:
        for edges in (item.get("spans") if isinstance(item, dict) else None) or [item]:
            spans.extend(_span(edges))
    return spans


def _marker_spans(label: dict[str, Any]) -> list[dict[str, int]]:
    return [span for marker in label.get("markers") or [] for span in _span(marker)]
