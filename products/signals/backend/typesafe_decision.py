import math
import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from time import perf_counter
from typing import Literal, TypedDict, TypeVar

from django.conf import settings

import structlog
import posthoganalytics
from prometheus_client import Counter, Histogram

from posthog.egress.cloudflare_ai.transport import cloudflare_ai_request

logger = structlog.get_logger(__name__)

MODEL_MODE_FLAG = "signals-typesafe-mode"
ModelMode = Literal["traditional-only", "typesafe-shadow", "traditional-shadow", "typesafe-only"]
CLOUDFLARE_MODEL = "typesafe/jev"
TYPESAFE_DIRECT_INPUT_USD_PER_MILLION = 0.042
TIMEOUT_SECONDS = 3.0

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
    "TypeSafe input tokens reported by Cloudflare.",
    ["stage"],
)
_DIRECT_LIST_COST = Counter(
    "signals_typesafe_decision_direct_list_cost_usd",
    "TypeSafe input-token cost at TypeSafe's direct list price, not Cloudflare billing.",
    ["stage"],
)


class TypesafeResult(TypedDict):
    probability: float
    model: str
    input_tokens: int
    output_tokens: int
    latency_seconds: float
    category: str | None
    category_confidence: float | None


T = TypeVar("T")


async def _mode(team_id: int) -> ModelMode:
    if not settings.SIGNALS_TYPESAFE_CLOUDFLARE_ACCOUNT_ID or not settings.SIGNALS_TYPESAFE_CLOUDFLARE_API_TOKEN:
        return "traditional-only"
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


async def _query(stage: str, state: dict[str, object], instructions: str) -> TypesafeResult:
    import aiohttp  # noqa: PLC0415 — keeps the HTTP client off the Django startup path

    started = perf_counter()
    question = "actionable" if stage == "actionability" else "safe"
    questions: dict[str, object] = {question: {"type": "noul", "instructions": instructions}}
    if stage != "actionability":
        questions["category"] = {
            "type": "choice",
            "instructions": "Which safety category best describes the content? Choose none when no category applies.",
            "criteria": SAFETY_CATEGORIES,
        }
    payload: dict[str, object] = {
        "model": CLOUDFLARE_MODEL,
        "input": {"state": state, "questions": questions},
    }
    timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
        response = await cloudflare_ai_request(
            session,
            account_id=settings.SIGNALS_TYPESAFE_CLOUDFLARE_ACCOUNT_ID,
            api_token=settings.SIGNALS_TYPESAFE_CLOUDFLARE_API_TOKEN,
            source="signals_decision",
            payload=payload,
        )
        async with response:
            response.raise_for_status()
            body = await response.json()
    if not isinstance(body, dict):
        raise ValueError("Cloudflare AI returned a non-object response")
    result = body.get("result", body)
    if not isinstance(result, dict):
        raise ValueError("Cloudflare AI returned an invalid result")
    answers = result["answers"]
    if not isinstance(answers, dict):
        raise ValueError("Cloudflare AI returned invalid answers")
    answer = answers[question]
    if not isinstance(answer, dict):
        raise ValueError("Cloudflare AI returned an invalid answer")
    probability = float(answer["noul"])
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("Cloudflare AI returned an invalid probability")
    category: str | None = None
    category_confidence: float | None = None
    if stage != "actionability":
        category_answer = answers["category"]
        if not isinstance(category_answer, dict):
            raise ValueError("Cloudflare AI returned an invalid category")
        category = category_answer["choice"]
        if not isinstance(category, str) or category not in SAFETY_CATEGORIES:
            raise ValueError("Cloudflare AI returned an unknown safety category")
        category_confidence = float(category_answer["confidence"])
        if not math.isfinite(category_confidence) or not 0 <= category_confidence <= 1:
            raise ValueError("Cloudflare AI returned an invalid category confidence")
    usage = result["usage"]
    if not isinstance(usage, dict):
        raise ValueError("Cloudflare AI returned invalid usage")
    input_tokens = int(usage["input_tokens"])
    output_tokens = int(usage["output_tokens"])
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("Cloudflare AI returned negative token usage")
    model = result["model"]
    if not isinstance(model, str) or not model.startswith("jev-"):
        raise ValueError("Cloudflare AI returned a different model")
    return {
        "probability": probability,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_seconds": perf_counter() - started,
        "category": category,
        "category_confidence": category_confidence,
    }


async def run_model_decision(
    *,
    team_id: int | None,
    stage: str,
    primary_model: str,
    source_id: str | None,
    source_product: str | None,
    state: dict[str, object],
    instructions: str,
    threshold: float,
    traditional: Callable[[], Awaitable[T]],
    verdict: Callable[[T], bool],
    typesafe_result: Callable[[bool, str | None], T],
    traditional_category: Callable[[T], str | None] | None = None,
) -> T:
    mode = await _mode(team_id) if team_id is not None else "traditional-only"
    if mode == "traditional-only":
        return await traditional()

    async def run_traditional() -> tuple[T | None, Exception | None, float]:
        started = perf_counter()
        try:
            return await traditional(), None, perf_counter() - started
        except Exception as error:
            return None, error, perf_counter() - started

    async def run_typesafe() -> tuple[TypesafeResult | None, Exception | None, float]:
        started = perf_counter()
        try:
            result = await _query(stage, state, instructions)
            return result, None, perf_counter() - started
        except Exception as error:
            logger.warning("TypeSafe call failed", stage=stage, error_type=type(error).__name__)
            return None, error, perf_counter() - started

    traditional_task = asyncio.create_task(run_traditional()) if mode != "typesafe-only" else None
    typesafe_task = asyncio.create_task(run_typesafe())
    if traditional_task is not None:
        (
            (traditional_result, traditional_error, traditional_latency),
            (
                typesafe,
                typesafe_error,
                typesafe_latency,
            ),
        ) = await asyncio.gather(traditional_task, typesafe_task)
    else:
        traditional_result, traditional_error, traditional_latency = None, None, None
        typesafe, typesafe_error, typesafe_latency = await typesafe_task

    traditional_verdict = None
    if traditional_result is not None:
        with suppress(Exception):
            traditional_verdict = verdict(traditional_result)
    typesafe_verdict = typesafe["probability"] >= threshold if typesafe is not None else None
    traditional_category_value = None
    if traditional_category is not None and traditional_result is not None:
        with suppress(Exception):
            traditional_category_value = traditional_category(traditional_result)
    typesafe_decision = None
    conversion_error = None
    if typesafe_verdict is not None and typesafe is not None:
        try:
            typesafe_decision = typesafe_result(typesafe_verdict, typesafe["category"])
        except Exception as error:
            conversion_error = error
            logger.warning("TypeSafe result conversion failed", stage=stage, error_type=type(error).__name__)
    if mode == "typesafe-shadow" or (mode == "traditional-shadow" and typesafe_decision is None):
        deciding_provider = "traditional" if mode == "typesafe-shadow" else "traditional_fallback"
        decision = traditional_result
        decision_error = traditional_error
    else:
        deciding_provider = "typesafe"
        decision = typesafe_decision
        decision_error = conversion_error or typesafe_error

    with suppress(Exception):
        if traditional_latency is not None:
            _LATENCY.labels(stage, "traditional").observe(traditional_latency)
        _LATENCY.labels(stage, "typesafe").observe(typesafe_latency)
        typesafe_status = (
            type(conversion_error).__name__
            if conversion_error is not None
            else "ok"
            if typesafe is not None
            else type(typesafe_error).__name__
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
            "traditional_status": "ok"
            if traditional_result is not None
            else type(traditional_error).__name__
            if traditional_error
            else "skipped",
            "traditional_latency_ms": traditional_latency * 1000 if traditional_latency is not None else None,
            "typesafe_status": typesafe_status,
            "typesafe_latency_ms": typesafe_latency * 1000,
            "typesafe_threshold": threshold,
        }
        if typesafe is not None:
            disagreement = traditional_verdict != typesafe_verdict if traditional_verdict is not None else None
            estimated_cost = typesafe["input_tokens"] * TYPESAFE_DIRECT_INPUT_USD_PER_MILLION / 1_000_000
            _INPUT_TOKENS.labels(stage).inc(typesafe["input_tokens"])
            _DIRECT_LIST_COST.labels(stage).inc(estimated_cost)
            if disagreement:
                _DISAGREEMENTS.labels(stage, str(traditional_verdict).lower(), str(typesafe_verdict).lower()).inc()
            properties.update(
                {
                    "typesafe_verdict": typesafe_verdict,
                    "disagreement": disagreement,
                    "typesafe_probability": typesafe["probability"],
                    "typesafe_model": typesafe["model"],
                    "typesafe_category": typesafe["category"],
                    "typesafe_category_confidence": typesafe["category_confidence"],
                    "category_disagreement": (
                        traditional_category_value != typesafe["category"]
                        if traditional_category_value is not None and typesafe["category"] is not None
                        else None
                    ),
                    "typesafe_input_tokens": typesafe["input_tokens"],
                    "typesafe_output_tokens": typesafe["output_tokens"],
                    "typesafe_direct_list_cost_usd": estimated_cost,
                }
            )
        posthoganalytics.capture(
            event="signals_typesafe_decision_evaluated",
            distinct_id=f"team-{team_id}",
            properties=properties,
        )
    if decision_error is not None:
        raise decision_error
    if decision is None:
        raise RuntimeError("Model decision returned no result")
    return decision
