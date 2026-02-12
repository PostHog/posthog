from typing import Any

from llm_gateway.callbacks.base import InstrumentedCallback
from llm_gateway.metrics.prometheus import (
    COST_BY_TEAM_USD,
    COST_CACHE_SAVINGS_USD,
    COST_INPUT_USD,
    COST_OUTPUT_USD,
    COST_USD,
    LLM_REQUESTS,
    LLM_RESPONSE_TIME,
    TOKENS_CACHE_CREATION,
    TOKENS_CACHE_READ,
    TOKENS_INPUT,
    TOKENS_OUTPUT,
    TOKENS_REASONING,
)
from llm_gateway.request_context import get_auth_user, get_product


class PrometheusCallback(InstrumentedCallback):
    """Callback for recording token and cost metrics to Prometheus."""

    callback_name = "prometheus"

    async def _on_success(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float, end_user_id: str | None
    ) -> None:
        standard_logging_object = kwargs.get("standard_logging_object", {})
        metadata = standard_logging_object.get("metadata", {}) or {}
        usage_object = metadata.get("usage_object", {}) or {}
        cost_breakdown = standard_logging_object.get("cost_breakdown", {}) or {}

        provider = standard_logging_object.get("custom_llm_provider", "unknown")
        model = standard_logging_object.get("model", "unknown")
        product = get_product()
        is_streaming = standard_logging_object.get("stream", False)

        input_tokens = standard_logging_object.get("prompt_tokens")
        output_tokens = standard_logging_object.get("completion_tokens")

        cache_read_tokens = usage_object.get("cache_read_input_tokens")
        cache_creation_tokens = usage_object.get("cache_creation_input_tokens")

        completion_details = usage_object.get("completion_tokens_details", {}) or {}
        reasoning_tokens = completion_details.get("reasoning_tokens")

        response_cost = standard_logging_object.get("response_cost")
        input_cost = cost_breakdown.get("input_cost")
        output_cost = cost_breakdown.get("output_cost")
        saved_cache_cost = standard_logging_object.get("saved_cache_cost")

        response_time = standard_logging_object.get("response_time")

        auth_user = get_auth_user()
        team_id = str(auth_user.team_id) if auth_user and auth_user.team_id else None

        LLM_REQUESTS.labels(provider=provider, model=model, product=product, streaming=str(is_streaming)).inc()

        if input_tokens is not None and 0 <= input_tokens <= 1_000_000:
            TOKENS_INPUT.labels(provider=provider, model=model, product=product).inc(input_tokens)
        if output_tokens is not None and 0 <= output_tokens <= 1_000_000:
            TOKENS_OUTPUT.labels(provider=provider, model=model, product=product).inc(output_tokens)
        if cache_read_tokens is not None and cache_read_tokens > 0:
            TOKENS_CACHE_READ.labels(provider=provider, model=model, product=product).inc(cache_read_tokens)
        if cache_creation_tokens is not None and cache_creation_tokens > 0:
            TOKENS_CACHE_CREATION.labels(provider=provider, model=model, product=product).inc(cache_creation_tokens)
        if reasoning_tokens is not None and reasoning_tokens > 0:
            TOKENS_REASONING.labels(provider=provider, model=model, product=product).inc(reasoning_tokens)

        if response_cost is not None and response_cost > 0:
            COST_USD.labels(provider=provider, model=model, product=product).inc(response_cost)
            COST_BY_TEAM_USD.inc(team_id, response_cost)
        if input_cost is not None and input_cost > 0:
            COST_INPUT_USD.labels(provider=provider, model=model, product=product).inc(input_cost)
        if output_cost is not None and output_cost > 0:
            COST_OUTPUT_USD.labels(provider=provider, model=model, product=product).inc(output_cost)
        if saved_cache_cost is not None and saved_cache_cost > 0:
            COST_CACHE_SAVINGS_USD.labels(provider=provider, model=model, product=product).inc(saved_cache_cost)

        if response_time is not None and response_time > 0:
            LLM_RESPONSE_TIME.labels(provider=provider, model=model, product=product).observe(response_time)
