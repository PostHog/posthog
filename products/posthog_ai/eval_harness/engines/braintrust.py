"""The Braintrust engine — the default (and currently only) ``EvalEngine``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from braintrust import EvalAsync, EvalCase
from braintrust.framework import EvalResultWithSummary, Evaluator, ReporterDef

from .base import EvalTaskFn
from .types import AggregateScore, CaseResult, EvalSummary, ExperimentResult


def _quiet_report_eval(evaluator: Evaluator, result: EvalResultWithSummary, verbose: bool, jsonl: bool) -> bool:
    return True


def _quiet_report_run(results: list[bool], verbose: bool, jsonl: bool) -> bool:
    return True


QUIET_REPORTER: ReporterDef = ReporterDef(
    name="quiet",
    report_eval=_quiet_report_eval,
    report_run=_quiet_report_run,
)
"""Reporter that keeps Braintrust's per-experiment tables out of the shared stream.

Its callbacks are called synchronously by ``EvalAsync`` and must not be coroutines."""


class BraintrustEngine:
    """Runs experiments on Braintrust and reports through it.

    These knobs are load-bearing invariants (they used to live in
    ``harness/AGENTS.md``); breaking one produces a hang or a silently wrong
    result rather than an exception:

    - **Never pass a ``timeout``.** ``EvalAsync``'s timeout wraps the whole task
      invocation, including time a case spends queued on the harness's own
      concurrency semaphores, so it would kill cases that never started. The
      per-case budget belongs in the ``asyncio.wait_for`` inside the run's
      ``_execute_case``, which starts only after slot acquisition.
    - **Never let ``max_concurrency`` bind.** It is set to the total case count
      (cases × trials) so the harness's semaphores are the only limiters.
    - **``QUIET_REPORTER``.** Suites share one stdout; the quiet reporter stops
      each experiment from dumping its own score table into the interleaved
      stream. Its callbacks are called synchronously by ``EvalAsync`` and must
      not be coroutines.
    - **``update=True``.** Experiment names stay runtime/model-agnostic so history
      lines up across runs; updating keeps that history rather than forking it.
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
        result = await EvalAsync(
            project_name,
            data=list(cases),
            task=task,
            scores=list(scorers),
            trial_count=trial_count,
            # Our global concurrency semaphores are the only limiters that should
            # bind. Braintrust's own per-suite limiter must never gate, so let it
            # admit every case at once — across all trials.
            max_concurrency=max(len(cases) * trial_count, 1),
            # Braintrust's timeout wraps the whole task invocation, including any
            # time a case spends queued on our concurrency semaphores — so a queued
            # case would be killed before it ever started. The real budget is the
            # ``asyncio.wait_for`` inside ``_execute_case``.
            timeout=None,
            # Suites share one stdout; the quiet reporter stops each experiment
            # from dumping its own score table into the interleaved stream.
            reporter=QUIET_REPORTER,
            update=True,
            is_public=is_public,
            no_send_logs=no_send_logs,
            # Experiment names stay runtime/model-agnostic so history lines up
            # across runs; the metadata is what lets Braintrust filter or compare.
            metadata=metadata,
        )
        return self._translate(result)

    def _translate(self, result: EvalResultWithSummary) -> ExperimentResult:
        """Map braintrust's ``EvalResultWithSummary`` onto the neutral model.

        ``score=None`` is preserved per-case (braintrust drops it from the
        aggregate); a task exception becomes ``CaseResult.error`` as a string so
        callers never re-handle a live ``Exception``; ``summary.raw`` is the
        braintrust summary's ``as_dict()`` so the jsonl export round-trips
        byte-for-byte through ``EvalSummary.as_json()``.
        """
        summary = result.summary
        return ExperimentResult(
            summary=EvalSummary(
                engine_name="braintrust",
                experiment_name=summary.experiment_name,
                scores={name: AggregateScore(name=s.name, score=s.score) for name, s in summary.scores.items()},
                experiment_url=summary.experiment_url,
                raw=summary.as_dict(),
            ),
            results=[
                CaseResult(
                    input=case.input,
                    output=case.output,
                    scores=dict(case.scores or {}),
                    expected=case.expected,
                    metadata=dict(case.metadata or {}),
                    error=None if case.error is None else str(case.error),
                )
                for case in result.results
            ],
        )
