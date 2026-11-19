"""Engine-neutral types at the harness/engine boundary.

Stdlib-only on purpose: no Braintrust, no Django, no pydantic. ``env_preflight``
imports ``EnvVarSpec`` from here, and it sits on the Django-free ``__main__``
import chain (see ``harness/AGENTS.md``), so nothing here may pull in a heavier
dependency.

Each ``EvalEngine`` translates its native result shapes into these so the run
base, reporting, and trace emission never see an engine-specific type.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class CaseSpec:
    """An engine-neutral eval case: JSON-safe ``input`` plus ``expected`` and
    ``metadata``. Each engine translates this to its native case type; the
    harness keeps callable rebinding (a case's ``setup`` hook) in ``cases_by_name``."""

    input: dict[str, Any]
    expected: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class CaseHooks(Protocol):
    """The per-case handle the engine passes to the task.

    ``metadata`` is a mutable dict the engine must persist onto
    ``CaseResult.metadata``.
    """

    @property
    def metadata(self) -> dict[str, Any]: ...


EvalTaskFn = Callable[[dict[str, Any], CaseHooks], Awaitable[dict[str, Any] | None]]
"""The per-case task the engine drives: it takes the JSON-safe case input and the
neutral ``CaseHooks`` and returns the scorer ``output`` dict (or ``None``)."""


class NullCaseHooks:
    """A metadata-only ``CaseHooks`` for tests and local engines."""

    def __init__(self) -> None:
        self._metadata: dict[str, Any] = {}

    @property
    def metadata(self) -> dict[str, Any]:
        return self._metadata


@dataclass(frozen=True)
class ExperimentSpec:
    """The single argument to ``run_experiment``. Bundling the knobs in one frozen
    spec means a new field (e.g. a baseline experiment id) breaks no engine or stub."""

    project_name: str
    cases: Sequence[CaseSpec]
    task: EvalTaskFn
    scorers: Sequence[Any]  # duck-typed: eval_async(output, expected, **kwargs) + _name()
    trial_count: int
    metadata: dict[str, Any]
    on_results: Callable[[ExperimentResult], Awaitable[None]] | None = None
    record_scorer_results: bool = False


@dataclass(frozen=True, kw_only=True, slots=True)
class ScorerResult:
    """A scorer outcome for reporting, independent of its normalized aggregate score."""

    status: Literal["ok", "error", "skipped", "not_applicable"]
    value: float | int | bool | list[str] | None = None
    reasoning: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    evaluator_trace_id: str | None = None
    evaluated_at: datetime | None = None


@dataclass(frozen=False)
class CaseResult:
    """One scored case (or case × trial): the engine-neutral ``EvalResult``.

    ``scores`` maps scorer name to its per-case score; ``None`` means the scorer
    skipped this case (excluded from aggregates). ``error`` is non-``None`` when
    the task or a scorer raised. ``error_kind`` distinguishes task failures,
    excluded from all score averages, from partial scorer failures.
    """

    input: dict[str, Any]
    output: Any
    scores: dict[str, float | None]
    expected: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    scorer_results: dict[str, ScorerResult] = field(default_factory=dict)
    trial_index: int | None = None
    error_kind: Literal["task", "scorer"] = "task"


@dataclass(frozen=True)
class AggregateScore:
    """A scorer's mean over the cases where it produced a non-``None`` score."""

    name: str
    score: float | None


@dataclass
class EvalSummary:
    """The per-experiment summary the reporting path consumes.

    ``raw`` is the engine-native summary payload; ``as_json`` passes it straight
    through so the ``eval_results.jsonl`` export stays byte-identical to what the
    engine would have written itself.
    """

    engine_name: str
    experiment_name: str
    scores: dict[str, AggregateScore]
    experiment_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> str:
        return json.dumps(self.raw)


@dataclass
class ExperimentResult:
    """What ``EvalEngine.run_experiment`` returns: the summary plus every case."""

    summary: EvalSummary
    results: list[CaseResult]


@dataclass(frozen=True)
class EnvVarSpec:
    """One environment variable an engine requires, surfaced in the preflight error.

    ``name`` is the literal variable name; ``description`` says what it is for so a
    missing variable reads as a one-line fix.
    """

    name: str
    description: str
