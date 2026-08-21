"""Scorers for the implementation step.

The gradeable artifact is a unified diff (:class:`ImplementationOutput`). Deterministic
scorers check that the change lands in the right files, stays out of the wrong ones, and
contains the expected edits. A live build/typecheck check and an LLM-judge of fix
correctness layer on top when enabled.
"""

from __future__ import annotations

from typing import Any

from products.signals.eval.agentic.datasets import EvalCase, ImplementationCase
from products.signals.eval.agentic.scoring import DeterministicScorer, Score


def _exp(case: EvalCase):
    assert isinstance(case, ImplementationCase)
    return case.expected


class FilesTouchedScorer(DeterministicScorer):
    """Did the diff touch a file matching an expected path substring?"""

    def __init__(self) -> None:
        super().__init__("expected_files_touched")

    def grade(self, case: EvalCase, output: Any) -> list[Score]:
        exp = _exp(case)
        if not exp.expected_file_substrings:
            return []
        files_blob = "\n".join(output.files_changed).lower()
        hits = [sub for sub in exp.expected_file_substrings if sub.lower() in files_blob]
        value = len(hits) / len(exp.expected_file_substrings)
        return [Score.numeric(self.name, value, threshold=1.0, reasoning=f"hit={hits} files={output.files_changed}")]


class ForbiddenFilesScorer(DeterministicScorer):
    """No forbidden files were touched."""

    def __init__(self) -> None:
        super().__init__("no_forbidden_files")

    def grade(self, case: EvalCase, output: Any) -> list[Score]:
        exp = _exp(case)
        if not exp.forbidden_file_substrings:
            return []
        files_blob = "\n".join(output.files_changed).lower()
        violations = [sub for sub in exp.forbidden_file_substrings if sub.lower() in files_blob]
        return [Score.boolean(self.name, not violations, reasoning=f"violations={violations}")]


class DiffKeywordScorer(DeterministicScorer):
    """Fraction of expected keywords present in the diff body."""

    def __init__(self) -> None:
        super().__init__("diff_keywords_present")

    def grade(self, case: EvalCase, output: Any) -> list[Score]:
        exp = _exp(case)
        if not exp.expected_diff_keywords:
            return []
        diff = output.diff.lower()
        hits = [kw for kw in exp.expected_diff_keywords if kw.lower() in diff]
        value = len(hits) / len(exp.expected_diff_keywords)
        missing = [kw for kw in exp.expected_diff_keywords if kw.lower() not in diff]
        return [
            Score.numeric(self.name, value, threshold=1.0, reasoning=f"missing={missing}" if missing else "all present")
        ]


class FilesChangedCountScorer(DeterministicScorer):
    """Number of files changed is within the case's expected bounds (scope check)."""

    def __init__(self) -> None:
        super().__init__("files_changed_count")

    def grade(self, case: EvalCase, output: Any) -> list[Score]:
        exp = _exp(case)
        n = len(output.files_changed)
        ok = n >= exp.min_files_changed
        if exp.max_files_changed is not None:
            ok = ok and n <= exp.max_files_changed
        bound = f">={exp.min_files_changed}" + (f", <={exp.max_files_changed}" if exp.max_files_changed else "")
        return [Score.boolean(self.name, ok, reasoning=f"changed={n} expected {bound}")]


def default_implementation_scorers() -> tuple[Any, ...]:
    return (
        FilesTouchedScorer(),
        ForbiddenFilesScorer(),
        DiffKeywordScorer(),
        FilesChangedCountScorer(),
    )
