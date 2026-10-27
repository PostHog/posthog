"""The LLM step of an activity summary update: one call, its tokens and its cost.

The call goes through `build_openai_client`, so the deployment picks the gateway: the Go AI gateway
when its settings are set, else the Python gateway on the `signals` route.
"""

import time
import datetime
from typing import Any

from openai import OpenAI, OpenAIError
from openai.types.chat import ChatCompletionMessageParam

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_openai_client, trace_id_from_seed

from products.signals.backend.activity_summary.prompt import (
    RESPONSE_FORMAT,
    MalformedSummaryError,
    normalize_summary,
    system_prompt,
    user_message,
)
from products.signals.backend.activity_summary.render import MAX_COMPLETION_TOKENS, PROFILE_MAX_CHARS

AI_PRODUCT = "activity_summary"
# Not a person: the gateway attributes every call to the pipeline.
PIPELINE_DISTINCT_ID = "signals_activity_summary"
DEFAULT_MODEL = "gpt-6-luna"
# One retry on a malformed or truncated answer. The SDK already retries a failed request on its own.
MAX_ATTEMPTS = 2
REQUEST_TIMEOUT_SECONDS = 120.0
TRUNCATED_FINISH_REASON = "length"


@frozen
class SummaryPrices:
    input_price_per_million_tokens: float | None
    output_price_per_million_tokens: float | None


# Per million tokens. A model that is not here gets a null cost, not a guess.
MODEL_PRICES: dict[str, SummaryPrices] = {
    DEFAULT_MODEL: SummaryPrices(input_price_per_million_tokens=0.10, output_price_per_million_tokens=0.50),
}


def cost_usd(tokens_in: int | None, tokens_out: int | None, prices: SummaryPrices | None) -> float | None:
    """None without both token counts and both prices, so an unknown usage or price records no guess."""
    if tokens_in is None or tokens_out is None or prices is None:
        return None
    if prices.input_price_per_million_tokens is None or prices.output_price_per_million_tokens is None:
        return None
    return (
        tokens_in * prices.input_price_per_million_tokens + tokens_out * prices.output_price_per_million_tokens
    ) / 1_000_000


@frozen
class SummaryOutcome:
    summary: dict[str, Any] | None
    # Null when no response reported its usage.
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int
    error: str | None


def gateway_client(team_id: int, user_id: int, as_of: datetime.date) -> OpenAI:
    return build_openai_client(
        "signals",
        ai_product=AI_PRODUCT,
        trace_id=trace_id_from_seed(f"{AI_PRODUCT}:{team_id}:{user_id}:{as_of.isoformat()}"),
        properties={"team_id": str(team_id)},
        distinct_id=PIPELINE_DISTINCT_ID,
    )


def _add(total: int | None, value: int | None) -> int | None:
    return value if total is None else total + (value or 0)


def summarize(
    client: OpenAI,
    *,
    rendered_input: str,
    previous_summary: dict[str, Any] | None,
    model: str,
    as_of: datetime.date,
    max_completion_tokens: int = MAX_COMPLETION_TOKENS,
    profile_max_chars: int = PROFILE_MAX_CHARS,
    computed: dict[str, Any] | None = None,
) -> SummaryOutcome:
    """One summary. Tokens and latency add up over the attempts, because the retry costs too.

    `computed` holds the refs the themes can cite. Without it, every theme is dropped."""
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_prompt(profile_max_chars)},
        {
            "role": "user",
            "content": user_message(rendered_input, previous_summary, as_of, profile_max_chars, computed),
        },
    ]
    tokens_in: int | None = None
    tokens_out: int | None = None
    error: str | None = None
    started = time.monotonic()
    for _ in range(MAX_ATTEMPTS):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                user=PIPELINE_DISTINCT_ID,
                response_format=RESPONSE_FORMAT,
                max_completion_tokens=max_completion_tokens,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except OpenAIError as api_error:
            error = f"api_error: {type(api_error).__name__}"
            break
        if response.usage is not None:
            tokens_in = _add(tokens_in, response.usage.prompt_tokens)
            tokens_out = _add(tokens_out, response.usage.completion_tokens)
        choice = response.choices[0] if response.choices else None
        try:
            if choice is not None and choice.finish_reason == TRUNCATED_FINISH_REASON:
                raise MalformedSummaryError("response was truncated")
            summary = normalize_summary(
                choice.message.content if choice is not None else None,
                had_previous_summary=previous_summary is not None,
                computed=computed,
                profile_max_chars=profile_max_chars,
            )
        except MalformedSummaryError as malformed:
            error = f"malformed_output: {malformed}"
            continue
        return SummaryOutcome(
            summary=summary,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=round((time.monotonic() - started) * 1000),
            error=None,
        )
    return SummaryOutcome(
        summary=None,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=round((time.monotonic() - started) * 1000),
        error=error,
    )
