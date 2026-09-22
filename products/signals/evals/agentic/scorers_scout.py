from __future__ import annotations

from typing import Any

from products.posthog_ai.eval_harness.log_parser import LogParser
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
        parser = LogParser.cached(output.raw_log)
        calls = [
            name for name in case.expected_query_tools if any(not call.is_error for call in parser.get_tool_calls(name))
        ]
        return [Score.boolean(self.name, bool(calls), reasoning=f"matching_queries={sorted(set(calls))}")]


def default_scout_scorers() -> tuple[Any, ...]:
    return (ScoutOutcomeScorer(), ScoutProjectDataScorer())
