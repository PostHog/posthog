"""The engine seam: how a built suite's cases actually get run and scored.

``_BaseEvalRun`` owns everything about a run *except* the experiment execution
itself — case building, the per-case task skeleton, local logging, and the
reporting/finalization path. The one thing it delegates is running the
experiment, so the execution/reporting backend can be swapped without touching
the run base or any suite.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

from braintrust import EvalCase, EvalHooks

from .types import ExperimentResult

EvalTaskFn = Callable[[dict[str, Any], EvalHooks], Awaitable[dict[str, Any] | None]]
"""The per-case task the engine drives: it takes the JSON-safe case input and the
Braintrust hooks and returns the scorer ``output`` dict (or ``None``)."""


class EvalEngine(Protocol):
    """Runs one experiment over a suite's cases and returns the scored, summarized
    result the reporting path (``_BaseEvalRun._finalize``) consumes.

    ``BraintrustEngine`` is the only implementation today. The seam exists so a
    future ``PostHogEvalsEngine`` — recording datasets, experiments, and scores
    into PostHog's own LLM analytics as the system of record — can slot in behind
    the same interface, without changing the run base or any suite.
    """

    async def run_experiment(
        self,
        *,
        project_name: str,
        cases: Sequence[EvalCase],
        task: EvalTaskFn,
        scorers: Sequence[Any],
        trial_count: int,
        is_public: bool,
        no_send_logs: bool,
        metadata: dict[str, Any],
    ) -> ExperimentResult:
        """Run every case (``trial_count`` times each) through ``task`` and
        ``scorers``, and return the engine-neutral result plus its per-scorer
        summary."""
        ...
