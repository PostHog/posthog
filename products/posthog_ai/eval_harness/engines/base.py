"""The engine seam: how a built suite's cases actually get run and scored.

``_BaseEvalRun`` owns everything about a run *except* the experiment execution
itself — case building, the per-case task skeleton, local logging, and the
reporting/finalization path. The one thing it delegates is running the
experiment, so the execution/reporting backend can be swapped without touching
the run base or any suite.
"""

from __future__ import annotations

from typing import Protocol

from .types import EvalTaskFn, ExperimentResult, ExperimentSpec

# Re-exported for callers that import ``EvalTaskFn`` from the engine seam; it now
# lives in ``types`` (retargeted at the neutral ``CaseHooks``).
__all__ = ["EvalEngine", "EvalTaskFn"]


class EvalEngine(Protocol):
    """Runs one experiment over a suite's cases and returns the scored, summarized
    result the reporting path (``_BaseEvalRun._finalize``) consumes.

    ``BraintrustEngine`` is the only implementation today. The seam exists so a
    future ``PostHogEvalsEngine`` — recording datasets, experiments, and scores
    into PostHog's own LLM analytics as the system of record — can slot in behind
    the same interface, without changing the run base or any suite.
    """

    async def run_experiment(self, spec: ExperimentSpec) -> ExperimentResult:
        """Run every case in ``spec`` (``trial_count`` times each) through the task
        and scorers, and return the engine-neutral result plus its per-scorer
        summary."""
        ...
