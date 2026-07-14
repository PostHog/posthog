"""Metric aggregation, console reporting, and PostHog capture.

Reuses the sibling grouping eval's :func:`capture_evaluation` so agentic eval results
land in the same ``$ai_evaluation`` event shape and are queryable with the same tooling
— just under ``$ai_eval_source = 'signals-agentic'`` and an experiment name per step.
"""

from __future__ import annotations

import sys
import uuid
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from products.signals.eval.agentic.results import SuiteResult
from products.signals.eval.capture import EvalMetric, capture_evaluation, deterministic_uuid

if TYPE_CHECKING:
    from posthoganalytics import Posthog

EVAL_SOURCE = "signals-agentic"


def aggregate(suite: SuiteResult) -> dict[str, dict[str, float]]:
    """Per-metric aggregates across the suite: count, mean value, pass rate."""
    by_metric: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for case in suite.cases:
        for score in case.scores:
            if score.status != "ok":
                continue
            by_metric[score.name].append((score.value, score.passed))
    out: dict[str, dict[str, float]] = {}
    for name, rows in sorted(by_metric.items()):
        n = len(rows)
        out[name] = {
            "n": float(n),
            "mean": sum(v for v, _ in rows) / n if n else 0.0,
            "pass_rate": sum(1 for _, p in rows if p) / n if n else 0.0,
        }
    return out


def _runtime_label(runtime: dict[str, str] | None) -> str:
    if not runtime:
        return ""
    parts = [runtime.get(k) for k in ("adapter", "model", "effort")]
    return "/".join(p for p in parts if p)


def print_report(suite: SuiteResult, *, run_id: str | None = None, file=sys.stderr) -> None:
    """Human-readable summary: per-case verdicts then per-metric aggregates."""
    line = "=" * 72
    print(f"\n{line}", file=file)
    header = f"Agentic eval — step={suite.step} mode={suite.mode}"
    if run_id:
        header += f" run_id={run_id}"
    print(header, file=file)
    print(line, file=file)
    for case in suite.cases:
        status = "ERROR" if case.error else ("PASS" if case.passed else "FAIL")
        runtime_label = _runtime_label(getattr(case, "runtime", None))
        runtime_note = f" [{runtime_label}]" if runtime_label else ""
        print(
            f"[{status}] {case.case_id}{runtime_note}  (score={case.weighted_score:.2f}, {case.duration_s:.1f}s)",
            file=file,
        )
        if case.error:
            print(f"        error: {case.error}", file=file)
        for score in case.scores:
            mark = {"ok": "✓" if score.passed else "✗", "skipped": "–", "error": "!"}.get(score.status, "?")
            detail = f" — {score.reasoning}" if score.reasoning else ""
            if score.error:
                detail += f" [error: {score.error}]"
            print(f"        {mark} {score.name}: {score.value:.2f}{detail}", file=file)
    print(line, file=file)
    errored = sum(1 for c in suite.cases for s in c.scores if s.status == "error")
    skipped = sum(1 for c in suite.cases for s in c.scores if s.status == "skipped")
    summary = f"cases: {len(suite.cases)}  pass_rate: {suite.pass_rate:.0%}  mean_score: {suite.mean_score:.2f}"
    if errored or skipped:
        summary += f"  (scores errored: {errored}, skipped: {skipped})"
    print(summary, file=file)
    for name, agg in aggregate(suite).items():
        print(f"  {name}: mean={agg['mean']:.2f} pass_rate={agg['pass_rate']:.0%} (n={int(agg['n'])})", file=file)
    print(line, file=file)


class _RunTaggedClient:
    """Injects run-identity properties into every capture without forking the shared capture shape."""

    def __init__(self, client: Posthog, extra: dict[str, Any]):
        self._client = client
        self._extra = extra

    def capture(self, *, distinct_id: str, event: str, properties: dict[str, Any]) -> None:
        self._client.capture(distinct_id=distinct_id, event=event, properties={**properties, **self._extra})


def _run_properties(run_id: str, mode: str, runtime: dict[str, str] | None) -> dict[str, Any]:
    props: dict[str, Any] = {"$ai_eval_run_id": run_id, "$ai_eval_mode": mode}
    if runtime:
        for key, prop in (
            ("adapter", "$ai_runtime_adapter"),
            ("model", "$ai_model"),
            ("effort", "$ai_reasoning_effort"),
        ):
            if runtime.get(key):
                props[prop] = runtime[key]
    return props


def capture_suite(
    client: Posthog,
    suite: SuiteResult,
    *,
    eval_type: str = "offline",
    dataset_id: str | None = None,
    run_id: str | None = None,
) -> None:
    """Emit one ``$ai_evaluation`` event per score, reusing the grouping eval's capture shape."""
    run_id = run_id or str(uuid.uuid4())
    experiment_id = deterministic_uuid(f"agentic/{suite.step}")
    for case in suite.cases:
        item_id = deterministic_uuid(f"agentic/{suite.step}/{case.case_id}")
        metrics = [
            EvalMetric(
                name=score.name,
                score=score.value if score.status == "ok" else None,
                score_min=score.score_min,
                score_max=score.score_max,
                result_type=score.score_type.value,
                reasoning=score.reasoning,
                status=score.status,
                error_message=score.error,
            )
            for score in case.scores
        ]
        if not metrics:
            if not case.error:
                continue
            # Crashed cases must still land in captured data, or live pass rates skew upward.
            metrics = [EvalMetric(name="case_error", status="error", reasoning=case.error, error_message=case.error)]
        tagged = _RunTaggedClient(client, _run_properties(run_id, suite.mode, getattr(case, "runtime", None)))
        capture_evaluation(
            tagged,  # type: ignore[arg-type]
            experiment_id=experiment_id,
            experiment_name=suite.step,
            item_id=item_id,
            item_name=case.case_id,
            metrics=metrics,
            input=case.input_repr,
            output=case.output_repr,
            expected=case.expected_repr,
            dataset_id=dataset_id,
            passed=case.passed,
            eval_type=eval_type,
            eval_source=EVAL_SOURCE,
        )
