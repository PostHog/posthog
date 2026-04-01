from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from fastapi import Request

    from llm_gateway.auth.models import AuthenticatedUser
    from llm_gateway.rate_limiting.runner import ThrottleRunner
    from llm_gateway.rate_limiting.throttles import ThrottleContext

logger = structlog.get_logger(__name__)

POSTHOG_PROPERTY_PREFIX = "x-posthog-property-"
POSTHOG_FLAG_PREFIX = "x-posthog-flag-"
POSTHOG_PROVIDER_HEADER = "x-posthog-provider"
POSTHOG_USE_BEDROCK_FALLBACK_HEADER = "x-posthog-use-bedrock-fallback"


@dataclass
class RequestContext:
    request_id: str
    product: str = "llm_gateway"
    posthog_properties: dict[str, str] | None = None
    posthog_flags: dict[str, str] | None = None


request_context_var: ContextVar[RequestContext | None] = ContextVar("request_context", default=None)
throttle_runner_var: ContextVar[ThrottleRunner | None] = ContextVar("throttle_runner", default=None)
throttle_context_var: ContextVar[ThrottleContext | None] = ContextVar("throttle_context", default=None)
auth_user_var: ContextVar[AuthenticatedUser | None] = ContextVar("auth_user", default=None)
time_to_first_token_var: ContextVar[float | None] = ContextVar("time_to_first_token", default=None)


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


def set_posthog_properties(properties: dict[str, str] | None) -> None:
    ctx = request_context_var.get()
    if ctx is None:
        return
    request_context_var.set(replace(ctx, posthog_properties=properties))


def get_posthog_properties() -> dict[str, str] | None:
    ctx = request_context_var.get()
    return ctx.posthog_properties if ctx else None


def set_posthog_flags(flags: dict[str, str] | None) -> None:
    ctx = request_context_var.get()
    if ctx is None:
        return
    request_context_var.set(replace(ctx, posthog_flags=flags))


def set_posthog_context(
    properties: dict[str, str] | None = None,
    flags: dict[str, str] | None = None,
) -> None:
    ctx = request_context_var.get()
    if ctx is None:
        return
    request_context_var.set(replace(ctx, posthog_properties=properties, posthog_flags=flags))


def get_posthog_flags() -> dict[str, str] | None:
    ctx = request_context_var.get()
    return ctx.posthog_flags if ctx else None


def _extract_headers_with_prefix(request: Request, prefix: str) -> dict[str, str]:
    result: dict[str, str] = {}
    prefix_lower = prefix.lower()
    for name, value in request.headers.items():
        if name.lower().startswith(prefix_lower):
            key = name[len(prefix) :].lower()
            result[key] = value
    return result


def extract_posthog_properties_from_headers(request: Request) -> dict[str, str]:
    return _extract_headers_with_prefix(request, POSTHOG_PROPERTY_PREFIX)


def extract_posthog_flags_from_headers(request: Request) -> dict[str, str]:
    return _extract_headers_with_prefix(request, POSTHOG_FLAG_PREFIX)


def extract_posthog_provider_from_headers(request: Request) -> str | None:
    provider = request.headers.get(POSTHOG_PROVIDER_HEADER)
    if provider is None:
        return None

    normalized_provider = provider.strip().lower()
    if not normalized_provider:
        raise ValueError(f"Invalid {POSTHOG_PROVIDER_HEADER} header value. Expected one of: anthropic, bedrock.")
    if normalized_provider not in {"anthropic", "bedrock"}:
        raise ValueError(
            f"Invalid {POSTHOG_PROVIDER_HEADER} header value '{provider}'. Expected one of: anthropic, bedrock."
        )
    return normalized_provider


def extract_posthog_use_bedrock_fallback_from_headers(request: Request) -> bool | None:
    use_bedrock_fallback = request.headers.get(POSTHOG_USE_BEDROCK_FALLBACK_HEADER)
    if use_bedrock_fallback is None:
        return None

    normalized_value = use_bedrock_fallback.strip().lower()
    if normalized_value == "true":
        return True
    if normalized_value == "false":
        return False
    raise ValueError(
        f"Invalid {POSTHOG_USE_BEDROCK_FALLBACK_HEADER} header value '{use_bedrock_fallback}'. Expected: true or false."
    )


def apply_posthog_context_from_headers(request: Request) -> None:
    properties = extract_posthog_properties_from_headers(request)
    flags = extract_posthog_flags_from_headers(request)

    if properties:
        set_posthog_properties(properties)
    if flags:
        set_posthog_flags(flags)


def set_throttle_context(runner: ThrottleRunner, context: ThrottleContext) -> None:
    throttle_runner_var.set(runner)
    throttle_context_var.set(context)


def get_auth_user() -> AuthenticatedUser | None:
    return auth_user_var.get()


def set_auth_user(user: AuthenticatedUser) -> None:
    auth_user_var.set(user)


def get_time_to_first_token() -> float | None:
    return time_to_first_token_var.get()


def set_time_to_first_token(ttft: float) -> None:
    time_to_first_token_var.set(ttft)


async def record_cost(cost: float, end_user_id: str | None = None) -> None:
    """Record cost for rate limiting. Call after response completes."""
    runner = throttle_runner_var.get()
    context = throttle_context_var.get()
    if runner and context:
        if end_user_id and not context.end_user_id:
            context.end_user_id = end_user_id
        await runner.record_cost(context, cost)
