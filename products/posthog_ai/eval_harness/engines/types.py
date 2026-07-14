"""Engine-neutral types at the harness/engine boundary.

Stdlib-only on purpose: no braintrust, no Django, no pydantic. ``env_preflight``
imports ``EnvVarSpec`` from here, and it sits on the Django-free ``__main__``
import chain (see ``harness/AGENTS.md``), so nothing here may pull in a heavier
dependency.

Each ``EvalEngine`` translates its native result shapes into these so the run
base, reporting, and trace emission never see a braintrust type.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CaseResult:
    """One scored case (or case × trial): the engine-neutral ``EvalResult``.

    ``scores`` maps scorer name to its per-case score; ``None`` means the scorer
    skipped this case (excluded from aggregates). ``error`` is non-``None`` when
    the task itself raised — an infra failure the engine excludes from score
    averages rather than scoring 0.
    """

    input: dict[str, Any]
    output: Any
    scores: dict[str, float | None]
    expected: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


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
