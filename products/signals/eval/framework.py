import uuid
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from posthoganalytics import Posthog
from posthoganalytics.ai.openai import OpenAI

DISTINCT_ID = "llma_eval"


def deterministic_uuid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"llma-eval:{name}"))


@dataclass
class EvalMetric:
    name: str
    version: str = "1"
    result_type: str = "binary"
    score: float | None = None
    score_min: float = 0
    score_max: float = 1
    reasoning: str | None = None
    status: str = "ok"
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class EvalCase:
    name: str
    input: dict[str, Any]
    expected: Any = None


@dataclass
class EvalResult:
    case: EvalCase
    output: Any = None
    metric: EvalMetric | None = None
    error: str | None = None


def capture_evaluation(
    client: Posthog,
    experiment_id: str,
    experiment_name: str,
    item_id: str,
    item_name: str,
    metric: EvalMetric,
    input: Any = None,
    output: Any = None,
    expected: Any = None,
) -> None:
    properties: dict[str, Any] = {
        "$ai_evaluation_type": "offline",
        "$ai_experiment_id": experiment_id,
        "$ai_experiment_name": experiment_name,
        "$ai_experiment_item_id": item_id,
        "$ai_experiment_item_name": item_name,
        "$ai_metric_name": metric.name,
        "$ai_metric_version": metric.version,
        "$ai_result_type": metric.result_type,
        "$ai_status": metric.status,
    }

    if metric.status == "ok" and metric.score is not None:
        properties["$ai_score"] = metric.score
        properties["$ai_score_min"] = metric.score_min
        properties["$ai_score_max"] = metric.score_max

    if metric.reasoning:
        properties["$ai_reasoning"] = metric.reasoning
    if input is not None:
        properties["$ai_input"] = str(input)
    if output is not None:
        properties["$ai_output"] = str(output)
    if expected is not None:
        properties["$ai_expected"] = str(expected)
    if metric.error_code:
        properties["$ai_error_code"] = metric.error_code
    if metric.error_message:
        properties["$ai_error_message"] = metric.error_message

    client.capture(
        distinct_id=DISTINCT_ID,
        event="$ai_evaluation",
        properties=properties,
    )


def run_eval(
    client: Posthog,
    openai_client: OpenAI,
    experiment_name: str,
    cases: list[EvalCase],
    task_fn: Callable[[OpenAI, EvalCase], Any],
    judge_fn: Callable[[OpenAI, EvalCase, Any], EvalMetric],
) -> list[EvalResult]:
    experiment_id = deterministic_uuid(experiment_name)
    results: list[EvalResult] = []

    for case in cases:
        result = EvalResult(case=case)

        try:
            result.output = task_fn(openai_client, case)
        except Exception as e:
            result.error = traceback.format_exc()
            result.metric = EvalMetric(
                name="error",
                status="error",
                error_code="task_error",
                error_message=str(e),
            )

        if result.error is None:
            try:
                result.metric = judge_fn(openai_client, case, result.output)
            except Exception as e:
                result.error = traceback.format_exc()
                result.metric = EvalMetric(
                    name="error",
                    status="error",
                    error_code="judge_error",
                    error_message=str(e),
                )

        if result.metric:
            capture_evaluation(
                client=client,
                experiment_id=experiment_id,
                experiment_name=experiment_name,
                item_id=deterministic_uuid(f"{experiment_name}:{case.name}"),
                item_name=case.name,
                metric=result.metric,
                input=case.input,
                output=result.output,
                expected=case.expected,
            )

        results.append(result)

    client.flush()

    print(f"\n{'=' * 60}")  # noqa: T201
    print(f"Eval: {experiment_name}")  # noqa: T201
    print(f"{'=' * 60}")  # noqa: T201
    for r in results:
        score_str = f"{r.metric.score}" if r.metric and r.metric.score is not None else "N/A"
        status = r.metric.status if r.metric else "unknown"
        print(f"  {r.case.name}: score={score_str} status={status}")  # noqa: T201
        if r.error:
            print(f"    error: {r.error.splitlines()[-1]}")  # noqa: T201
    print(f"{'=' * 60}\n")  # noqa: T201

    return results
