"""Typed deterministic scoring used by the Signals datasets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from products.signals.eval.agentic.datasets import EvalCase


class ScoreType(str, Enum):
    BINARY = "binary"
    NUMERIC = "numeric"


@dataclass(frozen=False)
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
    """Grades a typed Signals step output."""

    name: str

    async def score(self, case: EvalCase, output: Any, ctx: ScoringContext) -> list[Score]: ...


@dataclass(frozen=False)
class ScoringContext:
    """Reserved for deterministic scorer dependencies."""

    repo_root: str | None = None
    extra: dict[str, Any] | None = None


class DeterministicScorer:
    """Base for scorers that grade with no I/O. Subclasses implement ``grade``."""

    def __init__(self, name: str):
        self.name = name

    async def score(self, case: EvalCase, output: Any, ctx: ScoringContext) -> list[Score]:
        return self.grade(case, output)

    def grade(self, case: EvalCase, output: Any) -> list[Score]:  # pragma: no cover - overridden
        raise NotImplementedError
