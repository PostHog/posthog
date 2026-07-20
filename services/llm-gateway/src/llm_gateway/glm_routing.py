"""Backend selection for GLM (`@cf/...`) traffic during the Cloudflare -> Modal migration.

Modal takes traffic opted in by the server-side `tasks-glm-modal-inference` flag or by the
env-configured fraction (caller-forwarded flag headers are deliberately ignored — they must not
force a backend operators turned off). No cross-backend retries — rollback is turning the
flag/fraction back down.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.responses import StreamingResponse

from llm_gateway.api.handler import (
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
from llm_gateway.cloudflare import (
    ensure_cloudflare_configured,
    ensure_cloudflare_model_allowed,
    is_cloudflare_configured,
    make_cloudflare_anthropic_call,
    make_cloudflare_completion_call,
    make_cloudflare_responses_call,
)
from llm_gateway.config import Settings, get_settings
from llm_gateway.flags import GLM_MODAL_FLAG, evaluate_flag
from llm_gateway.modal import (
    ensure_modal_configured,
    ensure_modal_model_allowed,
    is_modal_configured,
    is_modal_served_model,
    make_modal_anthropic_call,
    make_modal_completion_call,
    make_modal_responses_call,
    should_route_glm_to_modal,
)

LlmCall = Callable[..., Awaitable[Any]]


async def _route_to_modal(model: str, user: AuthenticatedUser, product: str, settings: Settings) -> bool:
    if not is_modal_served_model(model) or not is_modal_configured(settings):
        return False
    # Modal is the only configured backend — don't route to a Cloudflare 503.
    if not is_cloudflare_configured(settings):
        return True
    if should_route_glm_to_modal(model, product=product, user_key=str(user.user_id), settings=settings):
        return True
    # Server-side flag evaluation only — a caller-forwarded flag header must not be able to force a
    # backend the operators turned off. Evaluated last, since it can cost a remote roundtrip.
    return await evaluate_flag(GLM_MODAL_FLAG, user.distinct_id) or False


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
    return await handle_llm_request(
        request_data=dict(request_data),
        user=user,
        model=model,
        is_streaming=is_streaming,
        provider_config=provider_config,
        llm_call=make_call(api_base, api_key),
        product=product,
    )


async def _send_via_modal(
    request_data: dict[str, Any],
    user: AuthenticatedUser,
    is_streaming: bool,
    product: str,
    provider_config: ProviderConfig,
    make_call: Callable[[str, str, str], LlmCall],
    settings: Settings,
) -> dict[str, Any] | StreamingResponse:
    model = request_data["model"]
    ensure_modal_model_allowed(model)
    api_base, modal_key, modal_secret = ensure_modal_configured(settings)
    return await handle_llm_request(
        request_data=dict(request_data),
        user=user,
        model=model,
        is_streaming=is_streaming,
        provider_config=provider_config,
        llm_call=make_call(api_base, modal_key, modal_secret),
        product=product,
    )


async def _send_glm_request(
    request_data: dict[str, Any],
    user: AuthenticatedUser,
    is_streaming: bool,
    product: str,
    *,
    modal_config: ProviderConfig,
    cloudflare_config: ProviderConfig,
    make_modal_call: Callable[[str, str, str], LlmCall],
    make_cloudflare_call: Callable[[str, str], LlmCall],
) -> dict[str, Any] | StreamingResponse:
    model = request_data["model"]
    settings = get_settings()

    if await _route_to_modal(model, user, product, settings):
        return await _send_via_modal(request_data, user, is_streaming, product, modal_config, make_modal_call, settings)

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
        request_data,
        user,
        is_streaming,
        product,
        modal_config=MODAL_ANTHROPIC_CONFIG,
        cloudflare_config=CLOUDFLARE_ANTHROPIC_CONFIG,
        make_modal_call=make_modal_anthropic_call,
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
        cloudflare_config=CLOUDFLARE_OPENAI_CONFIG,
        make_modal_call=make_modal_completion_call,
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
        cloudflare_config=CLOUDFLARE_OPENAI_RESPONSES_CONFIG,
        make_modal_call=make_modal_responses_call,
        make_cloudflare_call=make_cloudflare_responses_call,
    )
