from __future__ import annotations

from typing import Any

from products.posthog_ai.eval_harness.acp_log import parse_log
from products.signals.evals.agentic.datasets import EvalCase, ScoutCase
from products.signals.evals.agentic.runners import ScoutOutput
from products.signals.evals.agentic.scoring import DeterministicScorer, Score


class ScoutOutcomeScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("scout_outcome_correct")

    def grade(self, case: EvalCase, output: ScoutOutput) -> list[Score]:
        assert isinstance(case, ScoutCase)
        expected = case.expected.expected_outcome
        acceptable = (expected,) if isinstance(expected, str) else expected
        return [
            Score.boolean(
                self.name, output.outcome in acceptable, reasoning=f"expected={acceptable} actual={output.outcome}"
            )
        ]


class ScoutProjectDataScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("project_data_queried")

    def grade(self, case: EvalCase, output: ScoutOutput) -> list[Score]:
        assert isinstance(case, ScoutCase)
        calls: list[str] = []
        for tool in parse_log(output.raw_log).tools:
            if tool.is_error:
                continue
            haystack = f"{tool.name} {' '.join(str(value) for value in tool.input.values())}".lower()
            calls.extend(name for name in case.expected_query_tools if name in haystack)
        return [Score.boolean(self.name, bool(calls), reasoning=f"matching_queries={sorted(set(calls))}")]


def default_scout_scorers() -> tuple[Any, ...]:
    return (ScoutOutcomeScorer(), ScoutProjectDataScorer())
