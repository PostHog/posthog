from __future__ import annotations

import os
import json
import asyncio
from typing import TYPE_CHECKING

from products.posthog_ai.backend.turn_suggestions.benchmark import Outcome, judge_case, load_cases
from products.posthog_ai.backend.turn_suggestions.classifier import SHOW_THRESHOLD
from products.posthog_ai.backend.turn_suggestions.judgment import build_judge_state, judge_model
from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.engines.types import ScorerResult
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPrivateEval
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer
from products.posthog_ai.evals.offline_config import offline_suite

if TYPE_CHECKING:
    from products.posthog_ai.eval_harness.harness.context import EvalContext

NO_SEND_LOGS = True

SUITE_KIND = SuiteKind.ONE_SHOT
BENCHMARK_CASES = {case.name: case for case in load_cases()}
CASES = [
    BaseEvalCase(
        name=case.name,
        prompt=json.dumps(build_judge_state(case.transcript)),
        expected={"acceptable": sorted(case.acceptable)},
        metadata={"category": case.category, "available": sorted(case.available)},
    )
    for case in BENCHMARK_CASES.values()
]


class OfferCorrectness(Scorer):
    def _name(self) -> str:
        return "offer_correctness"

    def _run_eval_sync(
        self, output: dict[str, object] | None, expected: dict[str, object] | None = None, **kwargs: object
    ) -> Score:
        outcome = (output or {}).get("outcome")
        if outcome is None or outcome == Outcome.FAILED:
            reason = (output or {}).get("error") or "Turn judge returned no judgment"
            return Score(
                name=self._name(),
                score=None,
                result=ScorerResult(status="error", error_code="judge_error", error_message=str(reason)),
            )
        return Score(
            name=self._name(),
            score=float(outcome in (Outcome.CORRECT, Outcome.EITHER)),
            metadata={"reason": outcome},
        )


async def eval_turn_suggestions(ctx: EvalContext) -> None:
    threshold = float(os.environ.get("TURN_SUGGESTIONS_EVAL_THRESHOLD", str(SHOW_THRESHOLD)))
    if not 0 <= threshold <= 1:
        raise ValueError("TURN_SUGGESTIONS_EVAL_THRESHOLD must be between 0 and 1")
    model = judge_model()

    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict[str, object]:
        result = await asyncio.to_thread(judge_case, BENCHMARK_CASES[case.name])
        return {
            "outcome": result.outcome(threshold),
            "picked": result.picked(threshold),
            "show_probability": result.judgment.show_probability if result.judgment else None,
            "threshold": threshold,
            "judge_model": model,
            "seconds": result.seconds,
            "error": result.error,
        }

    await OneShotPrivateEval(
        no_send_logs=NO_SEND_LOGS,
        experiment_name="turn-suggestions",
        cases=[
            case.model_copy(update={"metadata": {**case.metadata, "threshold": threshold, "judge_model": model}})
            for case in CASES
        ],
        task=task,
        scorers=[OfferCorrectness()],
        offline_suite=offline_suite(
            "turn_suggestions/eval_turn_suggestions::eval_turn_suggestions",
            metrics=["offer_correctness"],
            suite_kind=SUITE_KIND,
        ),
        send_to_posthog=True,
        ctx=ctx,
    )
