"""The LLM step of an activity summary update: one call, its tokens and its cost.

The call goes through `build_openai_client`, so the deployment picks the gateway: the Go AI gateway
when its settings are set, else the Python gateway on the `signals` route.
"""

import time
import datetime
from enum import StrEnum
from typing import Any, Literal

from openai import APIError, Omit, OpenAI, OpenAIError, omit
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_openai_client, trace_id_from_seed
from posthog.llm.openai_flex import FLEX_CAPABLE_MODELS, is_flex_recoverable

from products.signals.backend.activity_summary.prompt import (
    RESPONSE_FORMAT,
    EmptyProfileError,
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
# Flex runs on spare provider capacity, so it answers slower than the standard tier.
FLEX_REQUEST_TIMEOUT_SECONDS = 150.0
TRUNCATED_FINISH_REASON = "length"


class ServiceTier(StrEnum):
    STANDARD = "standard"
    FLEX = "flex"


@frozen
class SummaryVariant:
    """The model that builds a summary and the service tier the request asks for."""

    model: str
    service_tier: ServiceTier = ServiceTier.STANDARD


DEFAULT_VARIANT = SummaryVariant(model=DEFAULT_MODEL)


@frozen
class SummaryPrices:
    input_price_per_million_tokens: float | None
    output_price_per_million_tokens: float | None


# Per million tokens, from https://developers.openai.com/api/docs/pricing. A variant that is not here gets a null
# cost, not a guess. The cost counts cached input tokens at the full input price, so it is an upper bound on both tiers.
MODEL_PRICES: dict[SummaryVariant, SummaryPrices] = {
    DEFAULT_VARIANT: SummaryPrices(input_price_per_million_tokens=0.10, output_price_per_million_tokens=0.50),
    SummaryVariant(model="gpt-6.1-terra"): SummaryPrices(
        input_price_per_million_tokens=1.00, output_price_per_million_tokens=5.00
    ),
    SummaryVariant(model="gpt-6.1-terra", service_tier=ServiceTier.FLEX): SummaryPrices(
        input_price_per_million_tokens=0.50, output_price_per_million_tokens=2.50
    ),
}


def is_valid_variant(variant: SummaryVariant) -> bool:
    """A variant needs prices, so every call has a cost bound for the daily cap.

    A flex variant also needs a flex-capable model and a standard price, because a refused flex call retries on the
    standard tier."""
    if variant not in MODEL_PRICES:
        return False
    if variant.service_tier == ServiceTier.FLEX:
        return variant.model in FLEX_CAPABLE_MODELS and SummaryVariant(model=variant.model) in MODEL_PRICES
    return True


def billed_tiers(variant: SummaryVariant) -> tuple[ServiceTier, ...]:
    """The tiers that can answer a request of the variant."""
    if variant.service_tier == ServiceTier.FLEX:
        return (ServiceTier.FLEX, ServiceTier.STANDARD)
    return (variant.service_tier,)


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
    # The model answered a first summary with a headline and no profile. The update stores it as a skip.
    empty_profile: bool = False
    # Each response at the prices of the tier it asked for. Null when no response reported its usage, or when a
    # response came from a tier with no price.
    cost_usd: float | None = None
    # The tier the provider reports for the last response. Null when no response arrived or the gateway drops it.
    served_tier: str | None = None
    # A recoverable flex failure moved the rest of the summary to the standard tier.
    fell_back: bool = False


def gateway_client(team_id: int, user_id: int, as_of: datetime.date, *, variant: str | None = None) -> OpenAI:
    """`variant` keeps the trace of another build of the same pair and day, such as a backfill, apart."""
    seed = f"{AI_PRODUCT}:{team_id}:{user_id}:{as_of.isoformat()}"
    return build_openai_client(
        "signals",
        ai_product=AI_PRODUCT,
        trace_id=trace_id_from_seed(f"{seed}:{variant}" if variant else seed),
        properties={"team_id": str(team_id)},
        distinct_id=PIPELINE_DISTINCT_ID,
    )


def _add(total: int | None, value: int | None) -> int | None:
    return value if total is None else total + (value or 0)


def _add_cost(total: float | None, value: float | None) -> float | None:
    return None if total is None or value is None else total + value


def summarize(
    client: OpenAI,
    *,
    rendered_input: str,
    previous_summary: dict[str, Any] | None,
    variant: SummaryVariant,
    as_of: datetime.date,
    max_completion_tokens: int = MAX_COMPLETION_TOKENS,
    profile_max_chars: int = PROFILE_MAX_CHARS,
    computed: dict[str, Any] | None = None,
) -> SummaryOutcome:
    """One summary. Tokens, cost and latency add up over the attempts, because the retry costs too.

    A flex request that fails with an error that `is_flex_recoverable` accepts is sent again once on the standard
    tier, and the attempts after it stay on the standard tier. Any other API error ends the summary.
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
    cost: float | None = 0.0
    served_tier: str | None = None
    fell_back = False
    error: str | None = None
    tier = variant.service_tier
    started = time.monotonic()

    def create(service_tier: ServiceTier) -> ChatCompletion:
        flex = service_tier == ServiceTier.FLEX
        requested_tier: Literal["flex"] | Omit = "flex" if flex else omit
        # No SDK retry on flex: it would send the request again to the same starved tier, each time with the full
        # flex timeout, and the standard fallback would start too late for the pair timeout.
        return (client.with_options(max_retries=0) if flex else client).chat.completions.create(
            model=variant.model,
            messages=messages,
            user=PIPELINE_DISTINCT_ID,
            response_format=RESPONSE_FORMAT,
            max_completion_tokens=max_completion_tokens,
            service_tier=requested_tier,
            timeout=FLEX_REQUEST_TIMEOUT_SECONDS if flex else REQUEST_TIMEOUT_SECONDS,
        )

    def outcome(summary: dict[str, Any] | None, *, error: str | None, empty_profile: bool = False) -> SummaryOutcome:
        return SummaryOutcome(
            summary=summary,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=round((time.monotonic() - started) * 1000),
            error=error,
            empty_profile=empty_profile,
            cost_usd=cost if tokens_in is not None else None,
            served_tier=served_tier,
            fell_back=fell_back,
        )

    for _ in range(MAX_ATTEMPTS):
        try:
            try:
                response = create(tier)
            except APIError as flex_error:
                if tier != ServiceTier.FLEX or not is_flex_recoverable(flex_error):
                    raise
                tier = ServiceTier.STANDARD
                fell_back = True
                response = create(tier)
        except OpenAIError as api_error:
            error = f"api_error: {type(api_error).__name__}"
            break
        served_tier = response.service_tier
        if response.usage is not None:
            tokens_in = _add(tokens_in, response.usage.prompt_tokens)
            tokens_out = _add(tokens_out, response.usage.completion_tokens)
            prices = MODEL_PRICES.get(SummaryVariant(model=variant.model, service_tier=tier))
            cost = _add_cost(cost, cost_usd(response.usage.prompt_tokens, response.usage.completion_tokens, prices))
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
        except EmptyProfileError:
            return outcome(None, error=None, empty_profile=True)
        except MalformedSummaryError as malformed:
            error = f"malformed_output: {malformed}"
            continue
        return outcome(summary, error=None)
    return outcome(None, error=error)
