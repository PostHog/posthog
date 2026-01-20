from typing import Any

from llm_gateway.callbacks.base import InstrumentedCallback
from llm_gateway.request_context import record_output_tokens


class RateLimitCallback(InstrumentedCallback):
    """Callback for recording output tokens for rate limiting."""

    callback_name = "rate_limit"

    async def _on_success(self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float) -> None:
        standard_logging_object = kwargs.get("standard_logging_object", {})
        output_tokens = standard_logging_object.get("completion_tokens", 0)

        if output_tokens and output_tokens > 0:
            await record_output_tokens(output_tokens)
