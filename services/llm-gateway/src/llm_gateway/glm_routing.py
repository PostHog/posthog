"""Backend selection for GLM (`@cf/...`) traffic across Cloudflare, Modal, and Baseten.

Modal takes traffic opted in by its server-side flag or the environment-configured fraction.
Baseten takes traffic opted in by its server-side flag. Caller-forwarded flag headers cannot
select a backend. There are no cross-backend retries.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.responses import StreamingResponse

from llm_gateway.anthropic_request import drop_orphaned_clear_thinking
from llm_gateway.api.handler import (
    BASETEN_ANTHROPIC_CONFIG,
    BASETEN_OPENAI_CONFIG,
    BASETEN_OPENAI_RESPONSES_CONFIG,
    CLOUDFLARE_ANTHROPIC_CONFIG,
    CLOUDFLARE_OPENAI_CONFIG,
    CLOUDFLARE_OPENAI_RESPONSES_CONFIG,
    MODAL_ANTHROPIC_CONFIG,
    MODAL_OPENAI_CONFIG,
    MODAL_OPENAI_RESPONSES_CONFIG,
    ProviderConfig,
    handle_llm_request,
)
from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.baseten import (
    BASETEN_PUBLIC_MODEL,
    ensure_baseten_configured,
    is_baseten_configured,
    make_baseten_anthropic_call,
    make_baseten_completion_call,
    make_baseten_responses_call,
)
from llm_gateway.cloudflare import (
    ensure_cloudflare_configured,
    ensure_cloudflare_model_allowed,
    is_cloudflare_configured,
    make_cloudflare_anthropic_call,
    make_cloudflare_completion_call,
    make_cloudflare_responses_call,
)
from llm_gateway.config import Settings, get_settings
from llm_gateway.flags import GLM_BASETEN_FLAG, GLM_MODAL_FLAG, evaluate_flag
from llm_gateway.modal import (
    is_modal_configured,
    is_modal_served_model,
    make_modal_anthropic_call,
    make_modal_completion_call,
    make_modal_responses_call,
    should_route_glm_to_modal,
)
from llm_gateway.modal_routing import send_modal_request

LlmCall = Callable[..., Awaitable[Any]]

GLM_REASONING_EFFORTS: frozenset[str] = frozenset({"high", "max"})


def normalize_glm_anthropic_request(request_data: dict[str, Any], *, product: str) -> dict[str, Any]:
    """Make Claude runtime reasoning settings valid for GLM's Anthropic surface."""
    normalized = dict(request_data)
    output_config = normalized.get("output_config")
    effort = output_config.get("effort") if isinstance(output_config, dict) else None

    if effort in GLM_REASONING_EFFORTS:
        normalized["thinking"] = {"type": "adaptive"}

    return drop_orphaned_clear_thinking(normalized, product=product)


async def _route_to_modal(model: str, user: AuthenticatedUser, product: str, settings: Settings) -> bool:
    if not is_modal_served_model(model) or not is_modal_configured(settings):
        return False
    # Modal is the only configured backend — don't route to a Cloudflare 503.
    if not is_cloudflare_configured(settings):
        return True
    if should_route_glm_to_modal(model, product=product, user_key=str(user.user_id), settings=settings):
        return True
    return await evaluate_flag(GLM_MODAL_FLAG, user.distinct_id) or False


async def _route_to_baseten(model: str, user: AuthenticatedUser, settings: Settings) -> bool:
    if model != BASETEN_PUBLIC_MODEL or not is_baseten_configured(settings):
        return False
    return await evaluate_flag(GLM_BASETEN_FLAG, user.distinct_id) or False


async def _send_provider_request(
    request_data: dict[str, Any],
    user: AuthenticatedUser,
    is_streaming: bool,
    product: str,
    provider_config: ProviderConfig,
    llm_call: LlmCall,
) -> dict[str, Any] | StreamingResponse:
    return await handle_llm_request(
        request_data=dict(request_data),
        user=user,
        model=request_data["model"],
        is_streaming=is_streaming,
        provider_config=provider_config,
        llm_call=llm_call,
        product=product,
    )


async def _send_via_cloudflare(
    request_data: dict[str, Any],
    user: AuthenticatedUser,
    is_streaming: bool,
    product: str,
    provider_config: ProviderConfig,
    make_call: Callable[[str, str], LlmCall],
    settings: Settings,
) -> dict[str, Any] | StreamingResponse:
    model = request_data["model"]
    ensure_cloudflare_model_allowed(model)
    api_base, api_key = ensure_cloudflare_configured(settings)
    return await _send_provider_request(
        request_data, user, is_streaming, product, provider_config, make_call(api_base, api_key)
    )


async def _send_glm_request(
    request_data: dict[str, Any],
    user: AuthenticatedUser,
    is_streaming: bool,
    product: str,
    *,
    modal_config: ProviderConfig,
    baseten_config: ProviderConfig,
    cloudflare_config: ProviderConfig,
    make_modal_call: Callable[[str, str, str], LlmCall],
    make_baseten_call: Callable[[str, str], LlmCall],
    make_cloudflare_call: Callable[[str, str], LlmCall],
) -> dict[str, Any] | StreamingResponse:
    model = request_data["model"]
    settings = get_settings()

    if await _route_to_baseten(model, user, settings):
        api_base, api_key = ensure_baseten_configured(settings)
        return await _send_provider_request(
            request_data, user, is_streaming, product, baseten_config, make_baseten_call(api_base, api_key)
        )

    if await _route_to_modal(model, user, product, settings):
        return await send_modal_request(
            request_data, user, is_streaming, product, modal_config, make_modal_call, settings, handle_llm_request
        )

    return await _send_via_cloudflare(
        request_data, user, is_streaming, product, cloudflare_config, make_cloudflare_call, settings
    )


# Factories are passed at call time (not captured at import) so the module-level names stay the
# overridable seam.


async def send_glm_anthropic_messages(
    request_data: dict[str, Any],
    user: AuthenticatedUser,
    is_streaming: bool,
    product: str,
) -> dict[str, Any] | StreamingResponse:
    return await _send_glm_request(
        normalize_glm_anthropic_request(request_data, product=product),
        user,
        is_streaming,
        product,
        modal_config=MODAL_ANTHROPIC_CONFIG,
        baseten_config=BASETEN_ANTHROPIC_CONFIG,
        cloudflare_config=CLOUDFLARE_ANTHROPIC_CONFIG,
        make_modal_call=make_modal_anthropic_call,
        make_baseten_call=make_baseten_anthropic_call,
        make_cloudflare_call=make_cloudflare_anthropic_call,
    )


async def send_glm_chat_completions(
    request_data: dict[str, Any],
    user: AuthenticatedUser,
    is_streaming: bool,
    product: str,
) -> dict[str, Any] | StreamingResponse:
    return await _send_glm_request(
        request_data,
        user,
        is_streaming,
        product,
        modal_config=MODAL_OPENAI_CONFIG,
        baseten_config=BASETEN_OPENAI_CONFIG,
        cloudflare_config=CLOUDFLARE_OPENAI_CONFIG,
        make_modal_call=make_modal_completion_call,
        make_baseten_call=make_baseten_completion_call,
        make_cloudflare_call=make_cloudflare_completion_call,
    )


async def send_glm_responses(
    request_data: dict[str, Any],
    user: AuthenticatedUser,
    is_streaming: bool,
    product: str,
) -> dict[str, Any] | StreamingResponse:
    return await _send_glm_request(
        request_data,
        user,
        is_streaming,
        product,
        modal_config=MODAL_OPENAI_RESPONSES_CONFIG,
        baseten_config=BASETEN_OPENAI_RESPONSES_CONFIG,
        cloudflare_config=CLOUDFLARE_OPENAI_RESPONSES_CONFIG,
        make_modal_call=make_modal_responses_call,
        make_baseten_call=make_baseten_responses_call,
        make_cloudflare_call=make_cloudflare_responses_call,
    )
