from __future__ import annotations

from typing import TYPE_CHECKING, Any

from products.signals.evals.agentic.datasets import EvalCase, ResearchCase
from products.signals.evals.agentic.scoring import DeterministicScorer, Score

if TYPE_CHECKING:
    from products.signals.backend.report_generation.research import ReportResearchOutput


def _expectation(case: EvalCase):
    assert isinstance(case, ResearchCase)
    return case.expected


def _acceptable(expected: str | tuple[str | None, ...]) -> tuple[str | None, ...]:
    return (expected,) if isinstance(expected, str) else tuple(expected)


class ActionabilityScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("actionability_correct")

    def grade(self, case: EvalCase, output: ReportResearchOutput) -> list[Score]:
        exp = _expectation(case)
        if exp.expected_actionability is None:
            return []
        try:
            actual = output.effective_actionability().actionability.value
        except ValueError:
            return [Score.boolean(self.name, False, reasoning="no actionability assessment produced")]
        acceptable = _acceptable(exp.expected_actionability)
        ok = actual in acceptable
        return [Score.boolean(self.name, ok, reasoning=f"expected one of {acceptable} actual={actual}")]


class PriorityScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("priority_correct")

    def grade(self, case: EvalCase, output: ReportResearchOutput) -> list[Score]:
        exp = _expectation(case)
        if exp.expected_priority is None:
            return []
        prio = output.effective_priority()
        actual = prio.priority.value if prio else None
        acceptable = _acceptable(exp.expected_priority)
        ok = actual in acceptable
        return [Score.boolean(self.name, ok, reasoning=f"expected one of {acceptable} actual={actual}")]


class AlreadyAddressedScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("already_addressed_correct")

    def grade(self, case: EvalCase, output: ReportResearchOutput) -> list[Score]:
        exp = _expectation(case)
        if exp.expected_already_addressed is None:
            return []
        try:
            actual = output.effective_actionability().already_addressed
        except ValueError:
            return [Score.boolean(self.name, False, reasoning="no actionability assessment produced")]
        ok = actual == exp.expected_already_addressed
        return [Score.boolean(self.name, ok, reasoning=f"expected={exp.expected_already_addressed} actual={actual}")]


class FindingsVerifiedScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("findings_verified")

    def grade(self, case: EvalCase, output: ReportResearchOutput) -> list[Score]:
        exp = _expectation(case)
        if exp.expect_verified is None:
            return []
        findings = output.effective_findings()
        if not findings:
            return [Score.boolean(self.name, False, reasoning="no findings produced")]
        all_match = all(f.verified == exp.expect_verified for f in findings)
        verified_count = sum(1 for f in findings if f.verified)
        return [
            Score.boolean(
                self.name,
                all_match,
                reasoning=f"expected verified={exp.expect_verified}; {verified_count}/{len(findings)} verified",
            )
        ]


def default_research_scorers() -> tuple[Any, ...]:
    return (
        ActionabilityScorer(),
        PriorityScorer(),
        AlreadyAddressedScorer(),
        FindingsVerifiedScorer(),
    )
