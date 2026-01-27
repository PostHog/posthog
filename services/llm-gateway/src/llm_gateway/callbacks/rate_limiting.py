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

    if input_cost_per_token is None or output_cost_per_token is None:
        return None

    return input_tokens * input_cost_per_token + output_tokens * output_cost_per_token


class RateLimitCallback(InstrumentedCallback):
    """Callback for recording cost for rate limiting."""

    callback_name = "rate_limit"

    async def _on_success(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float, end_user_id: str | None
    ) -> None:
        standard_logging_object = kwargs.get("standard_logging_object", {})
        response_cost = standard_logging_object.get("response_cost")
        model = standard_logging_object.get("model", "unknown")
        provider = standard_logging_object.get("custom_llm_provider", "unknown")
        product = get_product()
        input_tokens = standard_logging_object.get("prompt_tokens")
        output_tokens = standard_logging_object.get("completion_tokens")

        if response_cost and response_cost > 0:
            logger.debug(
                "cost_recorded",
                cost=response_cost,
                end_user_id=end_user_id,
                model=model,
                provider=provider,
                product=product,
                source="response_cost",
            )
            await record_cost(response_cost, end_user_id)
            COST_RECORDED.labels(provider=provider, model=model, product=product).inc(response_cost)
            return

        estimated_cost = estimate_cost_from_tokens(model, input_tokens, output_tokens)

        if estimated_cost and estimated_cost > 0:
            logger.debug(
                "cost_recorded",
                cost=estimated_cost,
                end_user_id=end_user_id,
                model=model,
                provider=provider,
                product=product,
                source="token_estimation",
            )
            await record_cost(estimated_cost, end_user_id)
            COST_RECORDED.labels(provider=provider, model=model, product=product).inc(estimated_cost)
            COST_ESTIMATED.labels(provider=provider, model=model, product=product).inc()
            return

        settings = get_settings()
        fallback_cost = settings.default_fallback_cost_usd
        logger.warning(
            "cost_fallback_used",
            model=model,
            provider=provider,
            fallback_cost=fallback_cost,
            end_user_id=end_user_id,
            product=product,
        )
        await record_cost(fallback_cost, end_user_id)
        COST_FALLBACK_DEFAULT.labels(provider=provider, model=model, product=product).inc()
        COST_MISSING.labels(provider=provider, model=model, product=product).inc()
