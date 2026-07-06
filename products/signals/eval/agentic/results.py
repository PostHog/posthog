"""Result records produced by a harness run.

Kept in a leaf module (no harness/metrics imports) so both the harness that produces
them and the metrics layer that consumes them can depend on it without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from products.signals.eval.agentic.scoring import Score


@dataclass
class CaseResult:
    """The outcome of running and scoring one eval case."""

    case_id: str
    step: str
    mode: str
    scores: list[Score] = field(default_factory=list)
    input_repr: str = ""
    output_repr: str = ""
    expected_repr: str = ""
    error: str | None = None
    duration_s: float = 0.0

    @property
    def passed(self) -> bool:
        """A case passes when it produced an output and every non-skipped score passed."""
        if self.error is not None:
            return False
        graded = [s for s in self.scores if s.status == "ok"]
        return bool(graded) and all(s.passed for s in graded)

    @property
    def weighted_score(self) -> float:
        graded = [s for s in self.scores if s.status == "ok"]
        if not graded:
            return 0.0
        total_weight = sum(s.weight for s in graded) or 1.0
        return sum(s.value * s.weight for s in graded) / total_weight


@dataclass
class SuiteResult:
    """All case results for one step's eval run."""

    step: str
    mode: str
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        if not self.cases:
            return 0.0
        return sum(1 for c in self.cases if c.passed) / len(self.cases)

    @property
    def mean_score(self) -> float:
        if not self.cases:
            return 0.0
        return sum(c.weighted_score for c in self.cases) / len(self.cases)
