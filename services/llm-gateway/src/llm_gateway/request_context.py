from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm_gateway.rate_limiting.runner import ThrottleRunner
    from llm_gateway.rate_limiting.throttles import ThrottleContext

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
throttle_runner_var: ContextVar[ThrottleRunner | None] = ContextVar("throttle_runner", default=None)
throttle_context_var: ContextVar[ThrottleContext | None] = ContextVar("throttle_context", default=None)


def get_request_id() -> str:
    return request_id_var.get()


def set_request_id(request_id: str) -> None:
    request_id_var.set(request_id)


def set_throttle_context(runner: ThrottleRunner, context: ThrottleContext) -> None:
    throttle_runner_var.set(runner)
    throttle_context_var.set(context)


async def record_output_tokens(output_tokens: int) -> None:
    """Record actual output tokens for rate limiting. Call after streaming completes."""
    runner = throttle_runner_var.get()
    context = throttle_context_var.get()
    if runner and context:
        await runner.record_output_tokens(context, output_tokens)
