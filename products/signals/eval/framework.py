import uuid
import asyncio
import logging
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from posthoganalytics import Posthog
from posthoganalytics.ai.openai import AsyncOpenAI

logger = logging.getLogger(__name__)

DISTINCT_ID = "llma_eval"
DEFAULT_CONCURRENCY = 10


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


TaskFn = Callable[[AsyncOpenAI, EvalCase], Awaitable[Any]]
JudgeFn = Callable[[AsyncOpenAI, EvalCase, Any], Awaitable[EvalMetric]]


async def _run_case(
    semaphore: asyncio.Semaphore,
    openai_client: AsyncOpenAI,
    case: EvalCase,
    task_fn: TaskFn,
    judge_fn: JudgeFn,
) -> EvalResult:
    async with semaphore:
        result = EvalResult(case=case)

        try:
            result.output = await task_fn(openai_client, case)
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
                result.metric = await judge_fn(openai_client, case, result.output)
            except Exception as e:
                result.error = traceback.format_exc()
                result.metric = EvalMetric(
                    name="error",
                    status="error",
                    error_code="judge_error",
                    error_message=str(e),
                )

        return result


def _log_verbose(r: EvalResult) -> None:
    if r.case.expected is not None:
        output_answer = r.output.get("answer", r.output) if isinstance(r.output, dict) else r.output
        logger.warning("    expected: %s | got: %s", r.case.expected, output_answer)
    if isinstance(r.output, dict) and r.output.get("thoughts"):
        logger.warning("    thoughts: %s", r.output["thoughts"])
    if r.metric and r.metric.reasoning:
        logger.warning("    judge: %s", r.metric.reasoning)


async def run_eval(
    client: Posthog,
    openai_client: AsyncOpenAI,
    experiment_name: str,
    cases: list[EvalCase],
    task_fn: TaskFn,
    judge_fn: JudgeFn,
    max_concurrency: int = DEFAULT_CONCURRENCY,
    verbose: bool = True,
) -> list[EvalResult]:
    experiment_id = deterministic_uuid(experiment_name)
    semaphore = asyncio.Semaphore(max_concurrency)

    results = await asyncio.gather(
        *[_run_case(semaphore, openai_client, case, task_fn, judge_fn) for case in cases],
        return_exceptions=True,
    )

    eval_results: list[EvalResult] = []
    for i, r in enumerate(results):
        if isinstance(r, BaseException):
            r = EvalResult(
                case=cases[i],
                error=str(r),
                metric=EvalMetric(name="error", status="error", error_code="unexpected", error_message=str(r)),
            )
        eval_results.append(r)

        if r.metric:
            capture_evaluation(
                client=client,
                experiment_id=experiment_id,
                experiment_name=experiment_name,
                item_id=deterministic_uuid(f"{experiment_name}:{r.case.name}"),
                item_name=r.case.name,
                metric=r.metric,
                input=r.case.input,
                output=r.output,
                expected=r.case.expected,
            )

    client.flush()

    logger.warning("\n%s", "=" * 60)
    logger.warning("Eval: %s", experiment_name)
    logger.warning("=" * 60)
    for r in eval_results:
        score_str = f"{r.metric.score}" if r.metric and r.metric.score is not None else "N/A"
        status = r.metric.status if r.metric else "unknown"
        logger.warning("  %s: score=%s status=%s", r.case.name, score_str, status)
        if r.error:
            logger.error("    error: %s", r.error.splitlines()[-1])
        if verbose:
            _log_verbose(r)
    logger.warning("%s\n", "=" * 60)

    return eval_results
