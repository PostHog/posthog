"""Metric aggregation, console reporting, and PostHog capture.

Reuses the sibling grouping eval's :func:`capture_evaluation` so agentic eval results
land in the same ``$ai_evaluation`` event shape and are queryable with the same tooling
— just under ``$ai_eval_source = 'signals-agentic'`` and an experiment name per step.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from typing import TYPE_CHECKING

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


def print_report(suite: SuiteResult, *, file=sys.stderr) -> None:
    """Human-readable summary: per-case verdicts then per-metric aggregates."""
    line = "=" * 72
    print(f"\n{line}", file=file)
    print(f"Agentic eval — step={suite.step} mode={suite.mode}", file=file)
    print(line, file=file)
    for case in suite.cases:
        status = "ERROR" if case.error else ("PASS" if case.passed else "FAIL")
        print(f"[{status}] {case.case_id}  (score={case.weighted_score:.2f}, {case.duration_s:.1f}s)", file=file)
        if case.error:
            print(f"        error: {case.error}", file=file)
        for score in case.scores:
            mark = {"ok": "✓" if score.passed else "✗", "skipped": "–", "error": "!"}.get(score.status, "?")
            detail = f" — {score.reasoning}" if score.reasoning else ""
            print(f"        {mark} {score.name}: {score.value:.2f}{detail}", file=file)
    print(line, file=file)
    print(f"cases: {len(suite.cases)}  pass_rate: {suite.pass_rate:.0%}  mean_score: {suite.mean_score:.2f}", file=file)
    for name, agg in aggregate(suite).items():
        print(f"  {name}: mean={agg['mean']:.2f} pass_rate={agg['pass_rate']:.0%} (n={int(agg['n'])})", file=file)
    print(line, file=file)


def capture_suite(
    client: Posthog,
    suite: SuiteResult,
    *,
    eval_type: str = "offline",
    dataset_id: str | None = None,
) -> None:
    """Emit one ``$ai_evaluation`` event per score, reusing the grouping eval's capture shape."""
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
            continue
        capture_evaluation(
            client,
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
