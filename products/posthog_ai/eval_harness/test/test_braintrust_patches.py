import asyncio
from typing import Any

from django.test import SimpleTestCase

from braintrust import EvalAsync, EvalCase, Score
from braintrust_core.score import Scorer

from products.posthog_ai.eval_harness.engines import braintrust_patches  # noqa: F401 — applies the summary patch


class _SkipsOneCase(Scorer):
    def _name(self) -> str:
        return "skips"

    def _run_eval_sync(self, output: dict[str, Any] | None, expected: Any = None, **kwargs: Any) -> Score:
        if output and output.get("skip"):
            return Score(name="skips", score=None)
        return Score(name="skips", score=1.0)


class TestOfflineEvalSummary(SimpleTestCase):
    def test_summarizes_an_offline_run_whose_scorer_skips_a_case(self) -> None:
        async def task(input: dict[str, Any]) -> dict[str, Any]:
            return input

        cases: list[EvalCase[dict[str, Any], dict[str, Any]]] = [
            EvalCase(input={"skip": False}),
            EvalCase(input={"skip": True}),
        ]
        summary = asyncio.run(
            EvalAsync(
                "offline-summary-guard",
                data=cases,
                task=task,
                scores=[_SkipsOneCase()],
                no_send_logs=True,
            )
        ).summary

        self.assertEqual(summary.scores["skips"].score, 1.0)
