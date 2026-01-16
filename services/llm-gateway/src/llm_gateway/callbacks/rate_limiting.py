from typing import Any

from llm_gateway.callbacks.base import InstrumentedCallback
from llm_gateway.request_context import record_cost


class RateLimitCallback(InstrumentedCallback):
    """Callback for recording cost for rate limiting."""

    callback_name = "rate_limit"

    async def _on_success(self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float) -> None:
        standard_logging_object = kwargs.get("standard_logging_object", {})
        response_cost = standard_logging_object.get("response_cost")

        if response_cost and response_cost > 0:
            await record_cost(response_cost)
