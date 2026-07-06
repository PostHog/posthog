"""Scoring primitives: how a step's output is graded against ground truth.

A :class:`Scorer` takes the eval case (inputs + ground truth) and the step output and
returns one or more :class:`Score` objects. Scorers are intentionally small and
single-purpose (one concept per scorer) so a failing dimension is legible in the
results and so the set is easy to extend.

Two flavours, same interface:

- **Deterministic** scorers compare structured output to ground truth with no I/O
  (e.g. "did repo selection pick the expected repo", "did research touch the expected
  code path"). These are the regression backbone — cheap, stable, CI-friendly.
- **LLM-judge** scorers ask a model to grade a fuzzy quality (e.g. "is this summary a
  faithful, specific account of the findings"). They call the LLM gateway and only run
  when judging is enabled; absent that, the harness skips them.

``score`` is async so judge scorers can await the gateway; deterministic scorers simply
don't await anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from products.signals.eval.agentic.datasets import EvalCase


class ScoreType(str, Enum):
    BINARY = "binary"
    NUMERIC = "numeric"


@dataclass
class Score:
    """A single graded dimension of a step output.

    ``value`` is normalized to ``[score_min, score_max]`` (default 0..1). ``passed`` is
    the binary verdict used for pass-rate aggregation and the ``$ai_evaluation_result``
    field; for numeric scores it is derived from a threshold by the scorer.
    """

    name: str
    value: float
    passed: bool
    weight: float = 1.0
    score_type: ScoreType = ScoreType.BINARY
    reasoning: str | None = None
    score_min: float = 0.0
    score_max: float = 1.0
    status: str = "ok"
    error: str | None = None

    @classmethod
    def boolean(cls, name: str, ok: bool, *, weight: float = 1.0, reasoning: str | None = None) -> Score:
        return cls(name=name, value=1.0 if ok else 0.0, passed=ok, weight=weight, reasoning=reasoning)

    @classmethod
    def numeric(
        cls,
        name: str,
        value: float,
        *,
        threshold: float,
        weight: float = 1.0,
        score_min: float = 0.0,
        score_max: float = 1.0,
        reasoning: str | None = None,
    ) -> Score:
        return cls(
            name=name,
            value=value,
            passed=value >= threshold,
            weight=weight,
            score_type=ScoreType.NUMERIC,
            score_min=score_min,
            score_max=score_max,
            reasoning=reasoning,
        )

    @classmethod
    def errored(cls, name: str, error: str, *, weight: float = 1.0) -> Score:
        return cls(name=name, value=0.0, passed=False, weight=weight, status="error", error=error)


@runtime_checkable
class Scorer(Protocol):
    """Grades a step output. ``requires_judge`` marks scorers that call the LLM gateway."""

    name: str
    requires_judge: bool

    async def score(self, case: EvalCase, output: Any, ctx: ScoringContext) -> list[Score]: ...


@dataclass
class ScoringContext:
    """Ambient dependencies a scorer may use.

    ``judge`` is an optional callable that runs an LLM-as-judge grade; it is ``None`` when
    judging is disabled, in which case judge scorers are skipped by the harness rather than
    invoked. Keeping the dependency here (rather than constructing a client inside each
    scorer) keeps scorers pure and trivially unit-testable with a fake judge.
    """

    judge: JudgeFn | None = None
    repo_root: str | None = None
    extra: dict[str, Any] | None = None


@dataclass
class JudgeVerdict:
    """Structured result of an LLM-as-judge call."""

    passed: bool
    score: float
    reasoning: str


class JudgeFn(Protocol):
    async def __call__(self, *, system: str, prompt: str, rubric: str | None = None) -> JudgeVerdict: ...


class DeterministicScorer:
    """Base for scorers that grade with no I/O. Subclasses implement ``grade``."""

    requires_judge = False

    def __init__(self, name: str):
        self.name = name

    async def score(self, case: EvalCase, output: Any, ctx: ScoringContext) -> list[Score]:
        return self.grade(case, output)

    def grade(self, case: EvalCase, output: Any) -> list[Score]:  # pragma: no cover - overridden
        raise NotImplementedError


class JudgeScorer:
    """Base for LLM-as-judge scorers. Subclasses build the judge prompt from the output."""

    requires_judge = True

    def __init__(self, name: str):
        self.name = name

    async def score(self, case: EvalCase, output: Any, ctx: ScoringContext) -> list[Score]:
        if ctx.judge is None:
            return [Score(name=self.name, value=0.0, passed=False, status="skipped", reasoning="judge disabled")]
        system, prompt, rubric = self.build_judge_call(case, output)
        verdict = await ctx.judge(system=system, prompt=prompt, rubric=rubric)
        # The judge's own verdict is the pass source of truth; the score stays informational.
        return [
            Score(
                name=self.name,
                value=verdict.score,
                passed=verdict.passed,
                score_type=ScoreType.NUMERIC,
                reasoning=verdict.reasoning,
            )
        ]

    def build_judge_call(self, case: EvalCase, output: Any) -> tuple[str, str, str | None]:  # pragma: no cover
        raise NotImplementedError
