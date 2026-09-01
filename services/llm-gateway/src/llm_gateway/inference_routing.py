"""Route supported models to their configured inference providers.

GLM can be served by Cloudflare, Modal, or Baseten. DeepSeek V4 Flash is served only by
Baseten. Provider selection is internal to the gateway; caller-forwarded feature flag headers
cannot select a backend. There are no cross-provider retries.
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
    BASETEN_EXCLUSIVE_MODELS,
    BASETEN_GLM53_FLASH_PUBLIC_MODEL,
    BASETEN_GLM53_PUBLIC_MODEL,
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
    is_cloudflare_model,
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

# GLM models across all backends: these need the Claude-runtime reasoning rewrite on the
# Anthropic surface regardless of which provider serves them.
GLM_MODELS: frozenset[str] = frozenset(
    {BASETEN_PUBLIC_MODEL, BASETEN_GLM53_PUBLIC_MODEL, BASETEN_GLM53_FLASH_PUBLIC_MODEL}
)


def is_inference_routed_model(model: str) -> bool:
    """Whether this model id is served by the inference-routing layer rather than a native provider."""
    normalized = model.strip().lower()
    return is_cloudflare_model(normalized) or normalized in BASETEN_EXCLUSIVE_MODELS


def normalize_inference_routed_model(request_data: dict[str, Any]) -> dict[str, Any]:
    normalized = request_data["model"].strip().lower()
    if not is_inference_routed_model(normalized) or normalized == request_data["model"]:
        return request_data
    return {**request_data, "model": normalized}


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
    if not is_baseten_configured(settings):
        return False
    if model in BASETEN_EXCLUSIVE_MODELS:
        return True
    if model != BASETEN_PUBLIC_MODEL:
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


async def _send_inference_request(
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


async def send_inference_anthropic_messages(
    request_data: dict[str, Any],
    user: AuthenticatedUser,
    is_streaming: bool,
    product: str,
) -> dict[str, Any] | StreamingResponse:
    request_data = normalize_inference_routed_model(request_data)
    # Skip normalization only for Baseten-exclusive non-GLM models (DeepSeek); a Baseten-exclusive
    # GLM still needs the Claude-runtime reasoning rewrite.
    model = request_data["model"]
    if model in GLM_MODELS or model not in BASETEN_EXCLUSIVE_MODELS:
        request_data = normalize_glm_anthropic_request(request_data, product=product)

    return await _send_inference_request(
        request_data,
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


async def send_inference_chat_completions(
    request_data: dict[str, Any],
    user: AuthenticatedUser,
    is_streaming: bool,
    product: str,
) -> dict[str, Any] | StreamingResponse:
    request_data = normalize_inference_routed_model(request_data)
    return await _send_inference_request(
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


async def send_inference_responses(
    request_data: dict[str, Any],
    user: AuthenticatedUser,
    is_streaming: bool,
    product: str,
) -> dict[str, Any] | StreamingResponse:
    request_data = normalize_inference_routed_model(request_data)
    return await _send_inference_request(
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
