"""Capture reporting outcomes without changing the scores returned to the engine."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from datetime import UTC, datetime
from functools import wraps
from typing import TYPE_CHECKING, Any

from braintrust.framework import _scorer_name
from braintrust.score import is_scorer
from braintrust.util import bt_iscoroutinefunction

from ..engines.types import ScorerResult

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping


class ScorerRecorder:
    def __init__(self) -> None:
        self._results: dict[int, dict[str, ScorerResult]] = {}
        self._trial_indices: dict[int, int] = {}
        self._metadata: ContextVar[dict[str, Any]] = ContextVar("scorer_metadata")

    def register(self, metadata: dict[str, Any], trial_index: int) -> None:
        # Braintrust shares this dict between a trial's hooks, scorers and result.
        self._results[id(metadata)] = {}
        self._trial_indices[id(metadata)] = trial_index
        # Scorer tasks and Braintrust executor threads inherit their trial task's context.
        self._metadata.set(metadata)

    def _trace_id(self, metadata: dict[str, Any], name: str) -> str | None:
        traces = metadata.get("scorer_trace_ids")
        trace_id = traces.get(name) if isinstance(traces, dict) else None
        return trace_id if isinstance(trace_id, str) else None

    def _record(self, metadata: dict[str, Any], score: object, *, scorer_name: str) -> None:
        if isinstance(score, dict):
            name, value, score_metadata = score.get("name"), score.get("score"), score.get("metadata")
        else:
            name = getattr(score, "name", scorer_name)
            value = getattr(score, "score", score)
            score_metadata = getattr(score, "metadata", None)
        if not isinstance(name, str) or not isinstance(value, (float, int, type(None))):
            return
        score_metadata = dict(score_metadata) if isinstance(score_metadata, dict) else {}
        trace_id = self._trace_id(metadata, name) or self._trace_id(metadata, scorer_name)
        explicit_result = getattr(score, "result", None)
        if isinstance(explicit_result, ScorerResult):
            outcome = replace(
                explicit_result,
                metadata={**score_metadata, **explicit_result.metadata},
                evaluator_trace_id=explicit_result.evaluator_trace_id or trace_id,
                evaluated_at=explicit_result.evaluated_at or datetime.now(UTC),
            )
        else:
            reasoning = score_metadata.get("rationale") or score_metadata.get("reason")
            outcome = ScorerResult(
                status="skipped" if value is None else "ok",
                value=value,
                reasoning=reasoning if isinstance(reasoning, str) else None,
                metadata=score_metadata,
                evaluator_trace_id=trace_id,
                evaluated_at=datetime.now(UTC),
            )
        self._results[id(metadata)][name] = outcome

    def _record_error(self, metadata: dict[str, Any], name: str, error: Exception) -> None:
        self._results[id(metadata)][name] = ScorerResult(
            status="error",
            error_code="scorer_error",
            error_message=str(error),
            evaluator_trace_id=self._trace_id(metadata, name),
            evaluated_at=datetime.now(UTC),
        )

    def trial_index(self, metadata: dict[str, Any] | None) -> int | None:
        return self._trial_indices.get(id(metadata))

    def outcomes(self, metadata: dict[str, Any] | None, scores: Mapping[str, float | None]) -> dict[str, ScorerResult]:
        errors = metadata.get("scorer_errors", {}) if metadata is not None else {}
        return {
            name: outcome
            for name, outcome in self._results.get(id(metadata), {}).items()
            if name in scores or outcome.status == "error" and isinstance(errors, dict) and name in errors
        }

    @contextmanager
    def _capture(self, name: str) -> Iterator[Callable[[object], None]]:
        metadata = self._metadata.get()

        def record(result: object) -> None:
            for score in result if isinstance(result, (list, tuple)) else (result,):
                self._record(metadata, score, scorer_name=name)

        try:
            yield record
        except Exception as error:
            self._record_error(metadata, name, error)
            raise

    def _observe(self, scorer: Callable[..., Any], name: str) -> Callable[..., Any]:
        if bt_iscoroutinefunction(scorer):

            @wraps(scorer)
            async def observe_async(*args: Any, **kwargs: Any) -> Any:
                with self._capture(name) as record:
                    result = await scorer(*args, **kwargs)
                    record(result)
                    return result

            return observe_async

        @wraps(scorer)
        def observe_sync(*args: Any, **kwargs: Any) -> Any:
            with self._capture(name) as record:
                result = scorer(*args, **kwargs)
                record(result)
                return result

        return observe_sync

    def wrap(self, scorer: Any, index: int) -> Callable[..., Any]:
        scorer = scorer() if isinstance(scorer, type) and is_scorer(scorer) else scorer
        name = _scorer_name(scorer, index)
        wrapped = self._observe(getattr(scorer, "eval_async", scorer), name)
        wrapped.__name__ = name
        return wrapped
