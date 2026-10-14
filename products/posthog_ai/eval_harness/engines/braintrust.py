"""The Braintrust engine — the default (and currently only) ``EvalEngine``."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, ClassVar

from braintrust import EvalAsync, EvalCase, EvalHooks, Score
from braintrust.framework import EvalResultWithSummary, Evaluator, ReporterDef, _scorer_name, call_user_fn
from braintrust.score import is_score, is_scorer

# Imported for its side effect: braintrust's offline summary crashes on a skipped score.
from . import braintrust_patches  # noqa: F401
from .types import (
    AggregateScore,
    CaseResult,
    EnvVarSpec,
    EvalSummary,
    ExperimentResult,
    ExperimentSpec,
    ScorerResult,
    SpanKind,
)


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


class _ScorerRecorder:
    def __init__(self) -> None:
        self.results: dict[int, dict[str, ScorerResult]] = {}
        self.trial_indices: dict[int, int] = {}

    def register(self, metadata: dict[str, Any], trial_index: int) -> None:
        # Braintrust shares this dict between a trial's hooks, scorers and result.
        self.results[id(metadata)] = {}
        self.trial_indices[id(metadata)] = trial_index

    def trace_id(self, metadata: dict[str, Any], name: str) -> str | None:
        traces = metadata.get("scorer_trace_ids")
        trace_id = traces.get(name) if isinstance(traces, dict) else None
        return trace_id if isinstance(trace_id, str) else None

    def record(self, metadata: dict[str, Any], score: object) -> None:
        name = getattr(score, "name", None)
        value = getattr(score, "score", None)
        if not isinstance(name, str) or not isinstance(value, (float, int, type(None))):
            return
        score_metadata = getattr(score, "metadata", None)
        score_metadata = dict(score_metadata) if isinstance(score_metadata, dict) else {}
        explicit_result = getattr(score, "result", None)
        if isinstance(explicit_result, ScorerResult):
            outcome = replace(
                explicit_result,
                metadata={**score_metadata, **explicit_result.metadata},
                evaluator_trace_id=explicit_result.evaluator_trace_id or self.trace_id(metadata, name),
                evaluated_at=explicit_result.evaluated_at or datetime.now(UTC),
            )
        else:
            reasoning = score_metadata.get("rationale") or score_metadata.get("reason")
            outcome = ScorerResult(
                status="skipped" if value is None else "ok",
                value=value,
                reasoning=reasoning if isinstance(reasoning, str) else None,
                metadata=score_metadata,
                evaluator_trace_id=self.trace_id(metadata, name),
                evaluated_at=datetime.now(UTC),
            )
        self.results[id(metadata)][name] = outcome

    def record_error(self, metadata: dict[str, Any], name: str, error: Exception) -> None:
        self.results[id(metadata)][name] = ScorerResult(
            status="error",
            error_code="scorer_error",
            error_message=str(error),
            evaluator_trace_id=self.trace_id(metadata, name),
            evaluated_at=datetime.now(UTC),
        )


class _RecordingScorer:
    def __init__(self, scorer: Any, recorder: _ScorerRecorder, index: int) -> None:
        self._scorer = scorer
        self._recorder = recorder
        self._scorer_name = _scorer_name(scorer, index)

    def _name(self) -> str:
        return self._scorer_name

    async def eval_async(self, output: Any, expected: Any = None, **kwargs: Any) -> Score | list[Score]:
        metadata = kwargs["metadata"]
        try:
            scorer = getattr(self._scorer, "eval_async", self._scorer)
            result = await call_user_fn(
                asyncio.get_running_loop(),
                scorer,
                input=kwargs["input"],
                expected=expected,
                metadata=metadata,
                output=output,
            )
            if isinstance(result, dict):
                result = Score.from_dict(result)
            if isinstance(result, Iterable):
                result = list(result)
                if any(not is_score(score) for score in result):
                    raise ValueError("A scorer returning multiple results must return Score objects")
            elif not is_score(result):
                result = Score(name=self._name(), score=result)
            for score in result if isinstance(result, list) else [result]:
                self._recorder.record(metadata, score)
        except Exception as error:
            self._recorder.record_error(metadata, self._name(), error)
            raise
        return result


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
    def required_env(cls) -> tuple[EnvVarSpec, ...]:
        return (EnvVarSpec("BRAINTRUST_API_KEY", "records experiments and scores to Braintrust"),)

    async def run_experiment(self, spec: ExperimentSpec) -> ExperimentResult:
        recorder = _ScorerRecorder()

        async def bridged_task(input: dict[str, Any], hooks: EvalHooks) -> dict[str, Any] | None:
            recorder.register(hooks.metadata, hooks.trial_index)
            # Wrap braintrust's hooks so the suite task only ever sees neutral CaseHooks.
            return await spec.task(input, _BraintrustCaseHooks(hooks))

        cases = [EvalCase(input=case.input, expected=case.expected, metadata=case.metadata) for case in spec.cases]
        result = await EvalAsync(
            spec.project_name,
            data=cases,
            task=bridged_task,
            scores=[
                _RecordingScorer(
                    scorer() if isinstance(scorer, type) and is_scorer(scorer) else scorer, recorder, index
                )
                for index, scorer in enumerate(spec.scorers)
            ],
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
        return self._translate(result, recorder)

    def _translate(self, result: EvalResultWithSummary, recorder: _ScorerRecorder | None = None) -> ExperimentResult:
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
                    error=None if case.error is None else str(case.error),
                    scorer_results=recorder.results.get(id(case.metadata), {}) if recorder is not None else {},
                    trial_index=recorder.trial_indices.get(id(case.metadata)) if recorder is not None else None,
                )
                for case in result.results
            ],
        )
