from typing import Any

from llm_gateway.callbacks.base import InstrumentedCallback
from llm_gateway.metrics.prometheus import TOKENS_INPUT, TOKENS_OUTPUT
from llm_gateway.request_context import get_product


class PrometheusCallback(InstrumentedCallback):
    """Callback for recording token metrics to Prometheus."""

    callback_name = "prometheus"

    async def _on_success(self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float) -> None:
        standard_logging_object = kwargs.get("standard_logging_object", {})

        provider = standard_logging_object.get("custom_llm_provider", "unknown")
        model = standard_logging_object.get("model", "unknown")
        product = get_product()

        input_tokens = standard_logging_object.get("prompt_tokens")
        output_tokens = standard_logging_object.get("completion_tokens")

        if input_tokens is not None and 0 <= input_tokens <= 1_000_000:
            TOKENS_INPUT.labels(provider=provider, model=model, product=product).inc(input_tokens)
        if output_tokens is not None and 0 <= output_tokens <= 1_000_000:
            TOKENS_OUTPUT.labels(provider=provider, model=model, product=product).inc(output_tokens)
