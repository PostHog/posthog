from __future__ import annotations

import sys
import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from tqdm import tqdm

from posthog.dataclasses import frozen

from products.posthog_ai.eval_harness.engines.types import CaseResult, EvalSummary, ExperimentResult, ScorerResult
from products.posthog_ai.eval_harness.offline_results import (
    OfflineEvalPublisher,
    OfflineEvalSettings,
    OfflineUploadError,
)

if TYPE_CHECKING:
    from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite


@frozen
class EvalMetric:
    name: str
    score: float | None = None
    reasoning: str | None = None
    status: Literal["ok", "error", "skipped", "not_applicable"] = "ok"
    error_code: str | None = None
    error_message: str | None = None


class SignalsEvalRecorder:
    def __init__(
        self,
        suite: OfflineEvalSuite,
        *,
        disabled: bool = False,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.suite = suite
        self.disabled = disabled
        self.metadata = metadata or {}
        self.experiment_id = str(uuid4())
        self.started_at = datetime.now(UTC)
        self.cases: list[CaseResult] = []
        self.publisher: OfflineEvalPublisher | None = None
        if disabled:
            return
        try:
            settings = OfflineEvalSettings.from_env(suite)
            if settings is not None:
                self.publisher = OfflineEvalPublisher(settings, suite)
            else:
                self._report("uploads disabled: POSTHOG_OFFLINE_EVAL_API_KEY is not set")
        except OfflineUploadError as error:
            self._report(f"uploads disabled: {error}")

    def _report(self, message: str) -> None:
        tqdm.write(f"PostHog offline ({self.suite.key}): {message}", file=sys.stderr)

    @staticmethod
    def _metric_name(stage: str, metric: str) -> str:
        if metric == "correct_classification":
            if stage.endswith("-actionability-check"):
                return "actionability_correct_classification"
            return {
                "signal-safety-filter": "signal_safety_correct_classification",
                "report-safety-check": "report_safety_correct_classification",
                "scout-safety-filter": "scout_safety_correct_classification",
            }[stage]
        if stage == "grouping-aggregate" and metric == "group_recall":
            return "mean_group_recall"
        return metric

    def record(
        self,
        *,
        eval_name: str,
        item_name: str,
        metrics: list[EvalMetric],
        input: object = None,
        output: object = None,
        expected: object = None,
        passed: bool = True,
    ) -> None:
        if self.disabled:
            return
        if self.publisher is None:
            return
        outcomes = {name: ScorerResult(status="not_applicable") for name in self.suite.scorer_kinds}
        scores: dict[str, float | None] = {}
        for metric in metrics:
            name = self._metric_name(eval_name, metric.name)
            if name not in outcomes:
                raise ValueError(f"Unconfigured offline metric: {name}")
            scores[name] = metric.score
            outcomes[name] = ScorerResult(
                status="skipped" if metric.status == "ok" and metric.score is None else metric.status,
                value=metric.score if metric.status == "ok" else None,
                reasoning=metric.reasoning,
                error_code=metric.error_code,
                error_message=metric.error_message,
                evaluated_at=datetime.now(UTC),
            )
        self.cases.append(
            CaseResult(
                input={"name": f"{eval_name}/{item_name}", "input": input},
                output=output,
                expected=expected,
                scores=scores,
                scorer_results=outcomes,
                metadata={"stage": eval_name, "passed": passed},
            )
        )

    async def publish(self) -> str | None:
        if self.publisher is None or not self.cases:
            return None
        try:
            upload = self.publisher.prepare(
                experiment_id=self.experiment_id,
                experiment_name=self.suite.key,
                started_at=self.started_at,
                result=ExperimentResult(
                    summary=EvalSummary(engine_name="signals", experiment_name=self.suite.key, scores={}),
                    results=self.cases,
                ),
                metadata=self.metadata,
            )
            url = await asyncio.wait_for(self.publisher.publish(upload), timeout=60)
        except Exception as error:
            reason = str(error) if isinstance(error, OfflineUploadError) else type(error).__name__
            self._report(f"upload failed: {reason}. Results were not saved for retry.")
            return None
        self._report(f"uploaded: {url}")
        await self.publisher.tag(upload)
        return url
