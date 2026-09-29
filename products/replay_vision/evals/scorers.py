"""Deterministic scorers for the Replay Vision labeling benchmark suite.

Every case carries the question and each labeler's comparable answer under `expected["cell"]`, and the task
returns Replay Vision's comparable answer under `output["answer"]` (None when the scan gave none).
"""

from typing import Any

from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer
from products.replay_vision.backend.benchmark.labels import Question
from products.replay_vision.backend.benchmark.scoring import label_agreement, labeler_agreement


def _cell(expected: dict | None) -> tuple[Question, list[dict[str, Any]]] | None:
    cell = (expected or {}).get("cell")
    if not cell:
        return None
    return Question.model_validate(cell["question"]), cell["labels"]


class Answered(Scorer):
    """Replay Vision gave a comparable answer: a failed scan or an answer outside the question's options scores 0."""

    def _name(self) -> str:
        return "answered"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        answered = bool(output and output.get("answer") is not None)
        return Score(name=self._name(), score=float(answered), metadata={"error": (output or {}).get("error")})


class LabelAgreement(Scorer):
    """Mean agreement of Replay Vision's answer with each labeler's. No answer scores 0, so abstaining never pays."""

    def _name(self) -> str:
        return "label_agreement"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        cell = _cell(expected)
        if cell is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No labels for this case"})
        question, labels = cell
        answer = (output or {}).get("answer")
        if answer is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No answer"})
        score = label_agreement(question, answer, labels)
        return Score(name=self._name(), score=score, metadata={"labels": len(labels)})


class LabelerAgreement(Scorer):
    """How far the labelers agree with each other on this cell: the ceiling to read `label_agreement` against."""

    def _name(self) -> str:
        return "labeler_agreement"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        cell = _cell(expected)
        if cell is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No labels for this case"})
        question, labels = cell
        return Score(name=self._name(), score=labeler_agreement(question, labels), metadata={"labels": len(labels)})
