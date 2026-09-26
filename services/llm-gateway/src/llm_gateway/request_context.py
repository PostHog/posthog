from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextvars import Context, ContextVar, copy_context
from dataclasses import dataclass, replace
from functools import wraps
from typing import TYPE_CHECKING, cast
from uuid import UUID

import structlog
from structlog.types import EventDict, WrappedLogger

from llm_gateway.products.config import INTERNAL_RUN_SCOPE, get_product_config

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
TRACEPARENT_HEADER = "traceparent"

_VALID_PROVIDERS = ("anthropic", "bedrock", "cloudflare")
_PRIVATE_LOGGING_BOUND = "_gateway_private_logging_bound"


@dataclass
class RequestContext:
    request_id: str
    product: str = "llm_gateway"
    posthog_properties: dict[str, str] | None = None
    posthog_flags: dict[str, str] | None = None
    traceparent_trace_id: str | None = None


request_context_var: ContextVar[RequestContext | None] = ContextVar("request_context", default=None)
throttle_runner_var: ContextVar[ThrottleRunner | None] = ContextVar("throttle_runner", default=None)
throttle_context_var: ContextVar[ThrottleContext | None] = ContextVar("throttle_context", default=None)
auth_user_var: ContextVar[AuthenticatedUser | None] = ContextVar("auth_user", default=None)
time_to_first_token_var: ContextVar[float | None] = ContextVar("time_to_first_token", default=None)
effort_var: ContextVar[str | None] = ContextVar("effort", default=None)


def is_private_scout_request(user: AuthenticatedUser | None, product: str) -> bool:
    config = get_product_config(product)
    return bool(
        product == "signals"
        and config is not None
        and config.credit_bucket is None
        and user is not None
        and user.auth_method == "oauth_access_token"
        and user.sandbox_task_id
        and user.team_id is not None
        and user.application_id in (config.allowed_application_ids or frozenset())
        and INTERNAL_RUN_SCOPE in (user.scopes or [])
        and "scout_experiment_internal:read" in (user.scopes or [])
    )


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


def set_traceparent_trace_id(trace_id: str | None) -> None:
    ctx = request_context_var.get()
    if ctx is None:
        return
    request_context_var.set(replace(ctx, traceparent_trace_id=trace_id))


def get_traceparent_trace_id() -> str | None:
    ctx = request_context_var.get()
    return ctx.traceparent_trace_id if ctx else None


def _parse_traceparent_trace_id(value: str | None) -> str | None:
    if not value:
        return None
    parts = value.split("-")
    if len(parts) < 4:
        return None
    trace_id_hex = parts[1]
    # All-zero means "no trace id" per the W3C spec, not a usable value.
    if len(trace_id_hex) != 32 or set(trace_id_hex) == {"0"}:
        return None
    try:
        return str(UUID(hex=trace_id_hex))
    except ValueError:
        return None


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

    expected = f"Expected one of: {', '.join(_VALID_PROVIDERS)}."
    normalized_provider = provider.strip().lower()
    if not normalized_provider:
        raise ValueError(f"Invalid {POSTHOG_PROVIDER_HEADER} header value. {expected}")
    if normalized_provider not in _VALID_PROVIDERS:
        raise ValueError(f"Invalid {POSTHOG_PROVIDER_HEADER} header value '{provider}'. {expected}")
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


def rebuild_request_context(product: str) -> None:
    ctx = request_context_var.get()
    if ctx is None:
        set_request_context(RequestContext(request_id="", product=product))
        return
    set_request_context(replace(ctx, product=product))


def apply_posthog_context_from_headers(request: Request) -> None:
    properties = extract_posthog_properties_from_headers(request)
    flags = extract_posthog_flags_from_headers(request)

    if properties:
        set_posthog_properties(properties)
    if flags:
        set_posthog_flags(flags)
    set_traceparent_trace_id(_parse_traceparent_trace_id(request.headers.get(TRACEPARENT_HEADER)))


def set_throttle_context(runner: ThrottleRunner, context: ThrottleContext) -> None:
    throttle_runner_var.set(runner)
    throttle_context_var.set(context)


def get_auth_user() -> AuthenticatedUser | None:
    return auth_user_var.get()


def drop_private_scout_log(_logger: WrappedLogger, _method_name: str, event: EventDict) -> EventDict:
    if is_private_scout_request(get_auth_user(), get_product()):
        raise structlog.DropEvent
    return event


class PrivateScoutLogFilter(logging.Filter):
    def filter(self, _record: logging.LogRecord) -> bool:
        return not is_private_scout_request(get_auth_user(), get_product())


def _bind_logging_callback[**P, R](callback: Callable[P, R], context: Context) -> Callable[P, R]:
    @wraps(callback)
    def bound(*args: P.args, **kwargs: P.kwargs) -> R:
        return context.copy().run(callback, *args, **kwargs)

    return bound


def _bind_async_logging_callback[**P, R](
    callback: Callable[P, Awaitable[R]], context: Context
) -> Callable[P, Awaitable[R]]:
    @wraps(callback)
    async def bound(*args: P.args, **kwargs: P.kwargs) -> R:
        async def invoke() -> R:
            return await callback(*args, **kwargs)

        return await asyncio.create_task(invoke(), context=context.copy())

    return bound


def bind_private_logging_context(logging_obj: object | None) -> None:
    if not is_private_scout_request(get_auth_user(), get_product()):
        return
    if logging_obj is None or getattr(logging_obj, _PRIVATE_LOGGING_BOUND, False):
        return

    # LiteLLM stream handlers start threads without copying the authenticated request context.
    context = copy_context()
    for name in ("success_handler", "failure_handler"):
        callback = getattr(logging_obj, name, None)
        if callable(callback):
            setattr(logging_obj, name, _bind_logging_callback(cast(Callable[..., object], callback), context))
    for name in ("async_success_handler", "async_failure_handler"):
        callback = getattr(logging_obj, name, None)
        if callable(callback):
            setattr(
                logging_obj,
                name,
                _bind_async_logging_callback(cast(Callable[..., Awaitable[object]], callback), context),
            )
    setattr(logging_obj, _PRIVATE_LOGGING_BOUND, True)


def bind_private_stream_logging(stream: object) -> None:
    bind_private_logging_context(getattr(stream, "logging_obj", None) or getattr(stream, "litellm_logging_obj", None))


def set_auth_user(user: AuthenticatedUser) -> None:
    auth_user_var.set(user)


def get_time_to_first_token() -> float | None:
    return time_to_first_token_var.get()


def set_time_to_first_token(ttft: float) -> None:
    time_to_first_token_var.set(ttft)


def get_effort() -> str | None:
    return effort_var.get()


def set_effort(effort: str | None) -> None:
    effort_var.set(effort)


async def record_cost(cost: float, end_user_id: str | None = None) -> None:
    """Record cost for rate limiting. Call after response completes."""
    runner = throttle_runner_var.get()
    context = throttle_context_var.get()
    if runner and context:
        if end_user_id and not context.end_user_id:
            context.end_user_id = end_user_id
        await runner.record_cost(context, cost)
