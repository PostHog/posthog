from __future__ import annotations

import math
from time import perf_counter
from typing import Protocol, TypedDict

from django.conf import settings

from posthog.egress.cloudflare_ai.transport import cloudflare_ai_request

CLOUDFLARE_MODEL = "typesafe/jev"
TIMEOUT_SECONDS = 3.0


class TypesafeResult(TypedDict):
    probability: float
    model: str
    input_tokens: int
    output_tokens: int
    latency_seconds: float
    category: str | None
    category_confidence: float | None


class TypesafeClient(Protocol):
    async def query(self, *, state: dict[str, object], questions: dict[str, object]) -> TypesafeResult: ...


class CloudflareTypesafeClient:
    def __init__(self, account_id: str, api_token: str) -> None:
        self._account_id = account_id
        self._api_token = api_token

    async def query(self, *, state: dict[str, object], questions: dict[str, object]) -> TypesafeResult:
        import aiohttp  # noqa: PLC0415 — keeps the HTTP client off the Django startup path

        started = perf_counter()
        payload: dict[str, object] = {
            "model": CLOUDFLARE_MODEL,
            "input": {"state": state, "questions": questions},
        }
        timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            response = await cloudflare_ai_request(
                session,
                account_id=self._account_id,
                api_token=self._api_token,
                source="signals_decision",
                payload=payload,
            )
            async with response:
                response.raise_for_status()
                body = await response.json()
        return _parse_cloudflare_response(body, questions, perf_counter() - started)


def get_typesafe_client() -> TypesafeClient | None:
    account_id = settings.SIGNALS_TYPESAFE_CLOUDFLARE_ACCOUNT_ID
    api_token = settings.SIGNALS_TYPESAFE_CLOUDFLARE_API_TOKEN
    if not account_id or not api_token:
        return None
    return CloudflareTypesafeClient(account_id, api_token)


def _parse_cloudflare_response(body: object, questions: dict[str, object], latency_seconds: float) -> TypesafeResult:
    if not isinstance(body, dict):
        raise ValueError("Cloudflare AI returned a non-object response")
    result = body.get("result", body)
    if not isinstance(result, dict):
        raise ValueError("Cloudflare AI returned an invalid result")
    answers = result["answers"]
    if not isinstance(answers, dict):
        raise ValueError("Cloudflare AI returned invalid answers")
    question = "actionable" if "actionable" in questions else "safe"
    answer = answers[question]
    if not isinstance(answer, dict):
        raise ValueError("Cloudflare AI returned an invalid answer")
    probability = float(answer["noul"])
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("Cloudflare AI returned an invalid probability")
    category: str | None = None
    category_confidence: float | None = None
    if "category" in questions:
        category_answer = answers["category"]
        if not isinstance(category_answer, dict):
            raise ValueError("Cloudflare AI returned an invalid category")
        category = category_answer["choice"]
        if not isinstance(category, str):
            raise ValueError("Cloudflare AI returned an invalid category choice")
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
        "latency_seconds": latency_seconds,
        "category": category,
        "category_confidence": category_confidence,
    }
