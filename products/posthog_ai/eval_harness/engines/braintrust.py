"""The Braintrust engine — the default (and currently only) ``EvalEngine``."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, ClassVar

from braintrust import EvalAsync, EvalCase, EvalHooks
from braintrust.framework import EvalResultWithSummary, Evaluator, ReporterDef
from braintrust.logger import Span, SpanImpl

from ..scorers.recording import ScorerRecorder

# Imported for its side effect: braintrust's offline summary crashes on a skipped score.
from . import braintrust_patches  # noqa: F401
from .types import AggregateScore, CaseResult, EnvVarSpec, EvalSummary, ExperimentResult, ExperimentSpec, SpanKind

logger = logging.getLogger(__name__)


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
    on the eventual ``CaseResult.metadata``); ``start_span`` maps the neutral
    ``(name, kind)`` onto braintrust's ``start_span(name=, span_attributes=)`` and
    yields the braintrust ``Span``, whose ``.log`` already matches ``SpanHandle``.
    """

    def __init__(self, hooks: EvalHooks) -> None:
        self._hooks = hooks

    @property
    def metadata(self) -> dict[str, Any]:
        return self._hooks.metadata

    @contextmanager
    def start_span(self, name: str, kind: SpanKind) -> Iterator[Any]:
        with self._hooks.span.start_span(name=name, span_attributes={"type": kind}) as span:
            yield span


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
    - **``braintrust_patches``.** Importing that module replaces braintrust's
      offline summary, which crashes on a skipped score. See its docstring.
    """

    name: ClassVar[str] = "braintrust"
    supports_public_experiments: ClassVar[bool] = True

    @classmethod
    def required_env(cls, *, no_send_logs: bool = False) -> tuple[EnvVarSpec, ...]:
        if no_send_logs:
            return ()
        return (EnvVarSpec("BRAINTRUST_API_KEY", "records experiments and scores to Braintrust"),)

    @staticmethod
    def _persist_trial_metadata(result: ExperimentResult, trial_spans: dict[str, Span]) -> None:
        for case in result.results:
            if span := trial_spans.get(case.metadata.get("trial_id", "")):
                span.log(metadata=case.metadata)
        next(iter(trial_spans.values())).flush()

    async def run_experiment(self, spec: ExperimentSpec) -> ExperimentResult:
        recorder = ScorerRecorder() if spec.record_scorer_results else None
        trial_spans: dict[str, Span] = {}

        async def bridged_task(input: dict[str, Any], hooks: EvalHooks) -> dict[str, Any] | None:
            if recorder is not None:
                recorder.register(hooks.metadata, hooks.trial_index)
            # Wrap braintrust's hooks so the suite task only ever sees neutral CaseHooks.
            try:
                return await spec.task(input, _BraintrustCaseHooks(hooks))
            finally:
                if not spec.no_send_logs and isinstance(hooks.span, SpanImpl):
                    # The pinned SDK exposes only the task span. Its context token retains the trial root span.
                    parent = hooks.span._context_token.old_value
                    if isinstance(parent, Span) and (trial_id := hooks.metadata.get("trial_id")):
                        trial_spans[trial_id] = parent

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
            update=True,
            is_public=spec.is_public,
            no_send_logs=spec.no_send_logs,
            # Experiment names stay runtime/model-agnostic so history lines up
            # across runs; the metadata is what lets Braintrust filter or compare.
            metadata=spec.metadata,
        )
        translated = self._translate(result, recorder)
        if spec.on_results is not None:
            await spec.on_results(translated)
            if trial_spans:
                try:
                    await asyncio.to_thread(self._persist_trial_metadata, translated, trial_spans)
                except Exception:
                    logger.warning(
                        "Could not upload final trial metadata; completed eval results remain available", exc_info=True
                    )
        return translated

    def _translate(self, result: EvalResultWithSummary, recorder: ScorerRecorder | None = None) -> ExperimentResult:
        """Map braintrust's ``EvalResultWithSummary`` onto the neutral model.

        ``score=None`` is preserved per-case (the aggregate drops it, online
        through braintrust and offline through ``braintrust_patches``); a task
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
