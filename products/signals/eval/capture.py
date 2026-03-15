import uuid
from dataclasses import dataclass
from typing import Any

from posthoganalytics import Posthog

DISTINCT_ID = "llma_eval"


def deterministic_uuid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"llma-eval:{name}"))


@dataclass
class EvalMetric:
    name: str
    description: str | None = None
    version: str = "1"
    result_type: str = "binary"
    score: float | None = None
    score_min: float = 0
    score_max: float = 1
    reasoning: str | None = None
    status: str = "ok"
    error_code: str | None = None
    error_message: str | None = None


def capture_evaluation(
    client: Posthog,
    experiment_id: str,
    experiment_name: str,
    item_id: str,
    item_name: str,
    metrics: list[EvalMetric],
    input: Any = None,
    output: Any = None,
    expected: Any = None,
    dataset_id: str | None = None,
    passed: bool = True,
    eval_type: str = "offline",
    eval_source: str = "signals-grouping",
) -> None:
    for metric in metrics:
        properties: dict[str, Any] = {
            "$ai_eval_source": eval_source,
            "$ai_evaluation_type": eval_type,
            "$ai_experiment_id": experiment_id,
            "$ai_experiment_name": f"{eval_source}/{experiment_name}",
            "$ai_experiment_item_id": item_id,
            "$ai_experiment_item_name": item_name,
            "$ai_metric_name": metric.name,
            "$ai_metric_version": metric.version,
            "$ai_result_type": metric.result_type,
            "$ai_evaluation_result": 1.0 if passed else 0.0,
            "$ai_status": metric.status,
            "$ai_dataset_id": dataset_id,
        }

        if metric.description:
            properties["$ai_metric_description"] = metric.description
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
