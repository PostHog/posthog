from __future__ import annotations

from typing import Any

import litellm
import structlog

from llm_gateway.callbacks.base import InstrumentedCallback
from llm_gateway.config import get_settings
from llm_gateway.metrics.prometheus import COST_ESTIMATED, COST_FALLBACK_DEFAULT, COST_MISSING, COST_RECORDED
from llm_gateway.request_context import get_product, record_cost

logger = structlog.get_logger(__name__)


def estimate_cost_from_tokens(
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    """Estimate cost from token counts using litellm's model cost data."""
    if not model or input_tokens is None or output_tokens is None:
        return None

    model_info = litellm.model_cost.get(model)
    if not model_info:
        return None

    input_cost_per_token = model_info.get("input_cost_per_token")
    output_cost_per_token = model_info.get("output_cost_per_token")

    if not input_cost_per_token or not output_cost_per_token:
        return None

    return (input_tokens * input_cost_per_token) + (output_tokens * output_cost_per_token)


class RateLimitCallback(InstrumentedCallback):
    """Callback for recording cost for rate limiting."""

    callback_name = "rate_limit"

    async def _on_success(self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float) -> None:
        standard_logging_object = kwargs.get("standard_logging_object", {})
        response_cost = standard_logging_object.get("response_cost")
        model = standard_logging_object.get("model", "unknown")
        provider = standard_logging_object.get("custom_llm_provider", "unknown")
        product = get_product()

        if response_cost and response_cost > 0:
            await record_cost(response_cost)
            COST_RECORDED.labels(provider=provider, model=model, product=product).inc(response_cost)
            return

        input_tokens = standard_logging_object.get("prompt_tokens")
        output_tokens = standard_logging_object.get("completion_tokens")

        estimated_cost = estimate_cost_from_tokens(model, input_tokens, output_tokens)

        if estimated_cost and estimated_cost > 0:
            await record_cost(estimated_cost)
            COST_RECORDED.labels(provider=provider, model=model, product=product).inc(estimated_cost)
            COST_ESTIMATED.labels(provider=provider, model=model, product=product).inc()
            logger.info(
                "cost_estimated_from_tokens",
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost=estimated_cost,
            )
            return

        settings = get_settings()
        fallback_cost = settings.default_fallback_cost_usd
        await record_cost(fallback_cost)
        COST_FALLBACK_DEFAULT.labels(provider=provider, model=model, product=product).inc()
        COST_MISSING.labels(provider=provider, model=model, product=product).inc()
        logger.warning(
            "cost_fallback_default_used",
            model=model,
            provider=provider,
            fallback_cost=fallback_cost,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
