"""Scorers for the repository-selection step.

Graded against :class:`RepoSelectionExpectation`. The core verdict is whether the agent
picked the repo a developer would actually need to change — or correctly declined when no
candidate is the subject.
"""

from __future__ import annotations

from typing import Any

from products.signals.eval.agentic.datasets import EvalCase, RepoSelectionCase
from products.signals.eval.agentic.scoring import DeterministicScorer, Score


class RepoSelectionCorrectnessScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("repo_selected_correct")

    def grade(self, case: EvalCase, output: Any) -> list[Score]:
        assert isinstance(case, RepoSelectionCase)
        exp = case.expected
        actual = (output.repository or None) and output.repository.strip().lower()
        if exp.expect_null:
            ok = actual is None
            return [Score.boolean(self.name, ok, reasoning=f"expected no repo, got {actual!r}")]
        raw = exp.expected_repository
        acceptable = (raw,) if isinstance(raw, str) else tuple(raw or ())
        acceptable = tuple(r.lower() for r in acceptable)
        if not acceptable:
            # Fail closed: with no ground truth the scorer would pass any non-null pick.
            return [Score.errored(self.name, f"case {case.case_id!r} sets neither expected_repository nor expect_null")]
        ok = actual in acceptable
        return [Score.boolean(self.name, ok, reasoning=f"expected one of {acceptable} actual={actual!r}")]


class RepoSelectionReasonScorer(DeterministicScorer):
    """A selection should carry a non-trivial reason — empty reasoning is a smell."""

    def __init__(self) -> None:
        super().__init__("repo_reason_present")

    def grade(self, case: EvalCase, output: Any) -> list[Score]:
        reason = (output.reason or "").strip()
        return [Score.boolean(self.name, len(reason) >= 10, reasoning=f"reason_len={len(reason)}")]


def default_repo_selection_scorers() -> tuple[Any, ...]:
    return (RepoSelectionCorrectnessScorer(), RepoSelectionReasonScorer())
