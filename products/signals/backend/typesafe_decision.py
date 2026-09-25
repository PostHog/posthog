import math
import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from time import perf_counter
from typing import Generic, Literal, TypeVar

import structlog
import posthoganalytics
from prometheus_client import Counter, Histogram

from posthog.dataclasses import frozen

from products.ml_inference.backend.facade import api as decision_api
from products.ml_inference.backend.facade.contracts import (
    ChoiceAnswer,
    DecisionGatewayError,
    DecisionQuestion,
    DecisionRequest,
    JsonValue,
    NoulAnswer,
)
from products.ml_inference.backend.facade.enums import DecisionQuestionType

logger = structlog.get_logger(__name__)

MODEL_MODE_FLAG = "signals-typesafe-mode"
ModelMode = Literal["traditional-only", "typesafe-shadow", "traditional-shadow", "typesafe-only"]
JEV_MODEL = "posthog/hogference/jevk5-fp8-0.2"
JEV_INPUT_USD_PER_MILLION = 0.042
JEV_TIMEOUT_SECONDS = 3.0

ACTIONABILITY_THRESHOLD = 0.95
SIGNAL_SAFETY_THRESHOLD = 0.90
REPORT_SAFETY_THRESHOLD = 0.50
SAFETY_CATEGORIES = {
    "none": "No matching safety category",
    "instruction_override": "Attempts to replace the agent's operating instructions",
    "hidden_instructions": "Instructions concealed from a human reader",
    "encoded_payload": "Obfuscated content for the agent to decode and act on",
    "secret_exfiltration": "Sends secrets or customer data outside the team's systems",
    "remote_code_execution": "Fetches and runs code from outside the repository",
}

_CALLS = Counter(
    "signals_typesafe_decision_calls",
    "TypeSafe decisions by stage and outcome.",
    ["stage", "outcome"],
)
_DISAGREEMENTS = Counter(
    "signals_typesafe_decision_disagreements",
    "TypeSafe decisions that disagreed with the traditional verdict.",
    ["stage", "traditional_verdict", "typesafe_verdict"],
)
_LATENCY = Histogram(
    "signals_typesafe_decision_latency_seconds",
    "Traditional and TypeSafe model wall-clock latency.",
    ["stage", "provider"],
    buckets=(0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 12.8, 30, 120),
)
_INPUT_TOKENS = Counter(
    "signals_typesafe_decision_input_tokens",
    "Jev input tokens reported by the AI Gateway.",
    ["stage"],
)
_ESTIMATED_COST = Counter(
    "signals_typesafe_decision_estimated_cost_usd",
    "Jev input-token cost at the AI Gateway catalog price.",
    ["stage"],
)


T = TypeVar("T")


@frozen
class _SignalsModelCallResult(Generic[T]):
    value: T | None
    error: Exception | None
    latency_seconds: float


class SignalsDecisionError(RuntimeError):
    pass


@frozen
class SignalsDecision:
    probability: float
    model: str
    input_tokens: int
    category: str | None
    category_confidence: float | None


async def model_mode(team_id: int) -> ModelMode:
    try:
        value = await asyncio.to_thread(
            posthoganalytics.get_feature_flag,
            MODEL_MODE_FLAG,
            f"team-{team_id}",
            groups={"project": str(team_id)},
            group_properties={"project": {"id": team_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
        if value == "typesafe-shadow":
            return "typesafe-shadow"
        if value == "traditional-shadow":
            return "traditional-shadow"
        if value == "typesafe-only":
            return "typesafe-only"
    except Exception:
        logger.warning("TypeSafe mode flag check failed", team_id=team_id, exc_info=True)
    return "traditional-only"


async def _query(team_id: int, stage: str, state: dict[str, JsonValue], instructions: str) -> SignalsDecision:
    question_name = "actionable" if stage == "actionability" else "safe"
    questions = {
        question_name: DecisionQuestion(type=DecisionQuestionType.NOUL, instructions=instructions),
    }
    if stage != "actionability":
        questions["category"] = DecisionQuestion(
            type=DecisionQuestionType.CHOICE,
            instructions="Which safety category best describes the content? Choose none when no category applies.",
            criteria=SAFETY_CATEGORIES,
        )
    result = await asyncio.to_thread(
        decision_api.decide_when_available,
        DecisionRequest(
            team_id=team_id,
            state=state,
            questions=questions,
            model=JEV_MODEL,
            ai_product="signals",
        ),
        timeout_seconds=JEV_TIMEOUT_SECONDS,
    )
    answer = result.answers.get(question_name)
    if not isinstance(answer, NoulAnswer):
        raise ValueError("Jev returned an invalid yes/no answer")
    if not math.isfinite(answer.probability) or not 0 <= answer.probability <= 1:
        raise ValueError("Jev returned an invalid probability")
    category = None
    category_confidence = None
    if stage != "actionability":
        category_answer = result.answers.get("category")
        if not isinstance(category_answer, ChoiceAnswer):
            raise ValueError("Jev returned an invalid safety category")
        category = category_answer.choice
        category_confidence = category_answer.confidence
    if category is not None and category not in SAFETY_CATEGORIES:
        raise ValueError("Jev returned an unknown safety category")
    if category_confidence is not None and (
        not math.isfinite(category_confidence) or not 0 <= category_confidence <= 1
    ):
        raise ValueError("Jev returned an invalid safety category confidence")
    return SignalsDecision(
        probability=answer.probability,
        model=result.model,
        input_tokens=result.input_tokens,
        category=category,
        category_confidence=category_confidence,
    )


async def run_model_decision(
    *,
    team_id: int | None,
    stage: str,
    primary_model: str,
    source_id: str | None,
    source_product: str | None,
    state: dict[str, JsonValue],
    instructions: str,
    threshold: float,
    traditional: Callable[[], Awaitable[T]],
    verdict: Callable[[T], bool],
    typesafe_result: Callable[[bool, str | None], T],
    traditional_category: Callable[[T], str | None] | None = None,
    mode_override: ModelMode | None = None,
) -> T:
    if team_id is None:
        return await traditional()
    mode = mode_override or await model_mode(team_id)
    if mode == "traditional-only":
        return await traditional()

    async def run_traditional() -> _SignalsModelCallResult[T]:
        started = perf_counter()
        try:
            return _SignalsModelCallResult(
                value=await traditional(),
                error=None,
                latency_seconds=perf_counter() - started,
            )
        except Exception as error:
            return _SignalsModelCallResult(value=None, error=error, latency_seconds=perf_counter() - started)

    async def run_typesafe() -> _SignalsModelCallResult[SignalsDecision]:
        started = perf_counter()
        try:
            result = await _query(team_id, stage, state, instructions)
            return _SignalsModelCallResult(value=result, error=None, latency_seconds=perf_counter() - started)
        except Exception as error:
            logger.warning("TypeSafe call failed", stage=stage, error_type=type(error).__name__)
            return _SignalsModelCallResult(value=None, error=error, latency_seconds=perf_counter() - started)

    traditional_task = asyncio.create_task(run_traditional()) if mode != "typesafe-only" else None
    typesafe_task = asyncio.create_task(run_typesafe())
    traditional_call = None
    traditional_cancelled = False
    if mode == "typesafe-shadow":
        assert traditional_task is not None
        traditional_call, typesafe_call = await asyncio.gather(traditional_task, typesafe_task)
    else:
        try:
            typesafe_call = await typesafe_task
        except asyncio.CancelledError:
            # Awaiting typesafe_task cancels only that task, so the traditional call would outlive its caller.
            if traditional_task is not None:
                traditional_task.cancel()
                with suppress(asyncio.CancelledError):
                    await traditional_task
            raise

    typesafe = typesafe_call.value
    typesafe_verdict = (
        typesafe.probability >= threshold and typesafe.category in (None, "none") if typesafe is not None else None
    )
    typesafe_decision = None
    conversion_error = None
    if typesafe_verdict is not None and typesafe is not None:
        try:
            typesafe_decision = typesafe_result(typesafe_verdict, typesafe.category)
        except Exception as error:
            conversion_error = error
            logger.warning("TypeSafe result conversion failed", stage=stage, error_type=type(error).__name__)

    if mode == "traditional-shadow":
        assert traditional_task is not None
        if typesafe_decision is None or traditional_task.done():
            traditional_call = await traditional_task
        else:
            traditional_task.cancel()
            try:
                await traditional_task
            except asyncio.CancelledError:
                traditional_cancelled = True

    traditional_result = traditional_call.value if traditional_call is not None else None
    traditional_error = traditional_call.error if traditional_call is not None else None
    traditional_latency = traditional_call.latency_seconds if traditional_call is not None else None

    traditional_verdict = None
    if traditional_result is not None:
        with suppress(Exception):
            traditional_verdict = verdict(traditional_result)
    traditional_category_value = None
    if traditional_category is not None and traditional_result is not None:
        with suppress(Exception):
            traditional_category_value = traditional_category(traditional_result)
    if mode == "typesafe-shadow" or (mode == "traditional-shadow" and typesafe_decision is None):
        deciding_provider = "traditional" if mode == "typesafe-shadow" else "traditional_fallback"
        decision = traditional_result
        decision_error = traditional_error
    else:
        deciding_provider = "typesafe"
        decision = typesafe_decision
        decision_error = conversion_error or typesafe_call.error

    with suppress(Exception):
        if traditional_latency is not None:
            _LATENCY.labels(stage, "traditional").observe(traditional_latency)
        _LATENCY.labels(stage, "typesafe").observe(typesafe_call.latency_seconds)
        typesafe_status = (
            type(conversion_error).__name__
            if conversion_error is not None
            else "ok"
            if typesafe is not None
            else type(typesafe_call.error).__name__
        )
        _CALLS.labels(stage, typesafe_status).inc()
        properties: dict[str, object] = {
            "stage": stage,
            "source_id": source_id,
            "source_product": source_product,
            "mode": mode,
            "deciding_provider": deciding_provider,
            "traditional_model": primary_model,
            "traditional_verdict": traditional_verdict,
            "traditional_category": traditional_category_value,
            "traditional_status": "cancelled"
            if traditional_cancelled
            else "ok"
            if traditional_result is not None
            else type(traditional_error).__name__
            if traditional_error
            else "skipped",
            "traditional_latency_ms": traditional_latency * 1000 if traditional_latency is not None else None,
            "typesafe_status": typesafe_status,
            "typesafe_latency_ms": typesafe_call.latency_seconds * 1000,
            "typesafe_threshold": threshold,
        }
        if typesafe is not None:
            disagreement = traditional_verdict != typesafe_verdict if traditional_verdict is not None else None
            estimated_cost = typesafe.input_tokens * JEV_INPUT_USD_PER_MILLION / 1_000_000
            _INPUT_TOKENS.labels(stage).inc(typesafe.input_tokens)
            _ESTIMATED_COST.labels(stage).inc(estimated_cost)
            if disagreement:
                _DISAGREEMENTS.labels(stage, str(traditional_verdict).lower(), str(typesafe_verdict).lower()).inc()
            properties.update(
                {
                    "typesafe_verdict": typesafe_verdict,
                    "disagreement": disagreement,
                    "typesafe_probability": typesafe.probability,
                    "typesafe_model": typesafe.model,
                    "typesafe_category": typesafe.category,
                    "typesafe_category_confidence": typesafe.category_confidence,
                    "category_disagreement": (
                        traditional_category_value != typesafe.category
                        if traditional_category_value is not None and typesafe.category is not None
                        else None
                    ),
                    "typesafe_input_tokens": typesafe.input_tokens,
                    "typesafe_estimated_cost_usd": estimated_cost,
                }
            )
        posthoganalytics.capture(
            event="signals_typesafe_decision_evaluated",
            distinct_id=f"team-{team_id}",
            properties=properties,
        )
    if decision_error is not None:
        if mode == "typesafe-only":
            # The gateway error body can echo the state, which holds customer content.
            # Only the error type and status leave here, so callers cannot log the body.
            status = (
                f" (status {decision_error.status_code})" if isinstance(decision_error, DecisionGatewayError) else ""
            )
            raise SignalsDecisionError(f"Signals decision failed: {type(decision_error).__name__}{status}") from None
        raise decision_error
    if decision is None:
        if mode == "typesafe-only":
            raise SignalsDecisionError("Signals decision returned no result")
        raise RuntimeError("Model decision returned no result")
    return decision
