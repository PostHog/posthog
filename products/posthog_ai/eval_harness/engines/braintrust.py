"""The Braintrust engine — the default (and currently only) ``EvalEngine``."""

from __future__ import annotations

from typing import Any, ClassVar

from braintrust import EvalAsync, EvalCase, EvalHooks
from braintrust.framework import EvalResultWithSummary, Evaluator, ReporterDef

from ..scorers.recording import ScorerRecorder

# Imported for its side effect: braintrust's offline summary crashes on a skipped score.
from . import braintrust_patches  # noqa: F401
from .types import AggregateScore, CaseResult, EnvVarSpec, EvalSummary, ExperimentResult, ExperimentSpec


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


class _BraintrustCaseHooks:
    """Adapts braintrust's ``EvalHooks`` to the neutral ``CaseHooks``.

    ``metadata`` is a write-through onto the braintrust hooks (so mutations land
    on the eventual ``CaseResult.metadata``).
    """

    def __init__(self, hooks: EvalHooks) -> None:
        self._hooks = hooks

    @property
    def metadata(self) -> dict[str, Any]:
        return self._hooks.metadata


class BraintrustEngine:
    """Runs evaluations locally with Braintrust; results are never uploaded to it.

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
    - **``braintrust_patches``.** Importing that module replaces braintrust's
      offline summary, which crashes on a skipped score. See its docstring.
    """

    name: ClassVar[str] = "braintrust"

    @classmethod
    def required_env(cls) -> tuple[EnvVarSpec, ...]:
        return ()

    async def run_experiment(self, spec: ExperimentSpec) -> ExperimentResult:
        recorder = ScorerRecorder() if spec.record_scorer_results else None

        async def bridged_task(input: dict[str, Any], hooks: EvalHooks) -> dict[str, Any] | None:
            if recorder is not None:
                recorder.register(hooks.metadata, hooks.trial_index)
            # Wrap braintrust's hooks so the suite task only ever sees neutral CaseHooks.
            return await spec.task(input, _BraintrustCaseHooks(hooks))

        cases = [EvalCase(input=case.input, expected=case.expected, metadata=case.metadata) for case in spec.cases]
        result = await EvalAsync(
            spec.project_name,
            data=cases,
            task=bridged_task,
            scores=[recorder.wrap(scorer, index) for index, scorer in enumerate(spec.scorers)]
            if recorder is not None
            else list(spec.scorers),
            trial_count=spec.trial_count,
            # Our global concurrency semaphores are the only limiters that should
            # bind. Braintrust's own per-suite limiter must never gate, so let it
            # admit every case at once — across all trials.
            max_concurrency=max(len(cases) * spec.trial_count, 1),
            # Braintrust's timeout wraps the whole task invocation, including any
            # time a case spends queued on our concurrency semaphores — so a queued
            # case would be killed before it ever started. The real budget is the
            # ``asyncio.wait_for`` inside ``_execute_case``.
            timeout=None,
            # Suites share one stdout; the quiet reporter stops each experiment
            # from dumping its own score table into the interleaved stream.
            reporter=QUIET_REPORTER,
            no_send_logs=True,
            # Experiment names stay runtime/model-agnostic so history lines up
            # across runs; metadata is retained with the local results.
            metadata=spec.metadata,
        )
        translated = self._translate(result, recorder)
        if spec.on_results is not None:
            await spec.on_results(translated)
        return translated

    def _translate(self, result: EvalResultWithSummary, recorder: ScorerRecorder | None = None) -> ExperimentResult:
        """Map braintrust's ``EvalResultWithSummary`` onto the neutral model.

        ``score=None`` is preserved per-case (the local aggregate drops it
        through ``braintrust_patches``); a task
        exception becomes ``CaseResult.error`` as a string so
        callers never re-handle a live ``Exception``; ``summary.raw`` is the
        braintrust summary's ``as_dict()`` so the jsonl export round-trips
        byte-for-byte through ``EvalSummary.as_json()``.
        """
        summary = result.summary
        return ExperimentResult(
            summary=EvalSummary(
                engine_name=self.name,
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
                    scorer_results=recorder.outcomes(case.metadata, case.scores) if recorder is not None else {},
                    trial_index=recorder.trial_index(case.metadata) if recorder is not None else None,
                    error_kind="task" if case.error is not None else "scorer",
                    error=(
                        str(case.error)
                        if case.error is not None
                        else f"Scorer errors: {', '.join(case.metadata['scorer_errors'])}"
                        if case.metadata and case.metadata.get("scorer_errors")
                        else None
                    ),
                )
                for case in result.results
            ],
        )
