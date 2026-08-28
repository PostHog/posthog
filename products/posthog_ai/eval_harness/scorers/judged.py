"""Shared wiring for sandboxed LLM-judge scorers.

The harness runs every scorer through Braintrust's ``EvalAsync``, which always
dispatches via ``eval_async`` — so judges implement only the async branch, and
``AsyncOnlyScorerMixin`` turns the never-used sync branch into an explicit error
instead of a silently divergent code path.
"""

from __future__ import annotations

from typing import Any

from autoevals.llm import LLMClassifier

from .contract import AsyncOnlyScorerMixin, Score

# Re-exported for back-compat: AsyncOnlyScorerMixin now lives in the scorer contract.
__all__ = [
    "BINARY_CHOICE_SCORES",
    "GRADED_ALIGNMENT_CHOICE_SCORES",
    "JUDGE_MODEL",
    "AsyncOnlyScorerMixin",
    "JudgedScorer",
]

BINARY_CHOICE_SCORES = {"yes": 1.0, "no": 0.0}

GRADED_ALIGNMENT_CHOICE_SCORES = {
    "perfect": 1.0,
    "near_perfect": 0.9,
    "slightly_off": 0.75,
    "somewhat_misaligned": 0.5,
    "strongly_misaligned": 0.25,
    "useless": 0.0,
}

JUDGE_MODEL = "gpt-5.4"


class JudgedScorer(AsyncOnlyScorerMixin, LLMClassifier):
    """Base class for sandboxed LLM judges.

    Subclasses implement ``_prepare(output, expected)`` returning either a
    ``Score`` to short-circuit (no LLM call), or a dict with ``output`` — and
    optionally ``expected`` — to forward to the LLM judge as template variables.

    Both the short-circuit paths and judge-call exceptions map to
    ``score=0.0`` rather than ``score=None`` — Braintrust treats ``None`` as
    "skipped" and drops it from the aggregate, which silently hides broken
    judges and missing query inputs. We want those to surface as failing
    scores instead. Judges that should genuinely self-skip (e.g. the graded
    tool never ran and another scorer covers that) return ``Score(score=None)``
    from ``_prepare`` deliberately.
    """

    async def _run_eval_async(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        prepared = self._prepare(output, expected)
        if isinstance(prepared, Score):
            return prepared
        try:
            return await super()._run_eval_async(prepared["output"], prepared.get("expected"), **kwargs)
        except Exception as exc:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"judge error: {exc}"})

    def _prepare(self, output: Any, expected: Any) -> dict[str, Any] | Score:
        raise NotImplementedError
