from __future__ import annotations

from typing import Any

from braintrust.score import is_score

from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer


def test_contract_scorer_is_dispatchable_by_braintrust() -> None:
    class _S(Scorer):
        def _name(self) -> str:
            return "s"

        def _run_eval_sync(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
            return Score(name="s", score=1.0)

    # braintrust's EvalAsync only runs a scorer if it exposes eval_async; the
    # later pure-class flip must keep that surface, or every scorer stops firing.
    assert hasattr(_S(), "eval_async")


def test_contract_score_passes_braintrust_is_score() -> None:
    # is_score is braintrust's duck check (name/score/metadata/as_dict); a Score
    # that fails it is silently dropped from every experiment's results.
    assert is_score(Score(name="s", score=1.0))
