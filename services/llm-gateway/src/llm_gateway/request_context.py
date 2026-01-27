from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from llm_gateway.auth.models import AuthenticatedUser
    from llm_gateway.rate_limiting.runner import ThrottleRunner
    from llm_gateway.rate_limiting.throttles import ThrottleContext

logger = structlog.get_logger(__name__)


@dataclass
class RequestContext:
    request_id: str
    product: str = "llm_gateway"


request_context_var: ContextVar[RequestContext | None] = ContextVar("request_context", default=None)
throttle_runner_var: ContextVar[ThrottleRunner | None] = ContextVar("throttle_runner", default=None)
throttle_context_var: ContextVar[ThrottleContext | None] = ContextVar("throttle_context", default=None)
auth_user_var: ContextVar[AuthenticatedUser | None] = ContextVar("auth_user", default=None)


def get_request_context() -> RequestContext | None:
    return request_context_var.get()


def set_request_context(ctx: RequestContext) -> None:
    request_context_var.set(ctx)


def get_request_id() -> str:
    ctx = request_context_var.get()
    return ctx.request_id if ctx else ""


def get_product() -> str:
    ctx = request_context_var.get()
    return ctx.product if ctx else "llm_gateway"


def set_throttle_context(runner: ThrottleRunner, context: ThrottleContext) -> None:
    throttle_runner_var.set(runner)
    throttle_context_var.set(context)


def get_auth_user() -> AuthenticatedUser | None:
    return auth_user_var.get()


def set_auth_user(user: AuthenticatedUser) -> None:
    auth_user_var.set(user)


async def record_cost(cost: float, end_user_id: str | None = None) -> None:
    """Record cost for rate limiting. Call after response completes."""
    runner = throttle_runner_var.get()
    context = throttle_context_var.get()
    if runner and context:
        if end_user_id:
            context.end_user_id = end_user_id
        await runner.record_cost(context, cost)
