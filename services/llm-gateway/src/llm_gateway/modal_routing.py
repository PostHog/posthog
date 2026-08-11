from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.responses import StreamingResponse

from llm_gateway.anthropic_request import drop_orphaned_clear_thinking
from llm_gateway.api.handler import (
    MODAL_ANTHROPIC_CONFIG,
    MODAL_OPENAI_CONFIG,
    MODAL_OPENAI_RESPONSES_CONFIG,
    ProviderConfig,
    handle_llm_request,
)
from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.config import Settings, get_settings
from llm_gateway.modal import (
    ensure_modal_model_allowed,
    ensure_modal_model_configured,
    make_modal_anthropic_call,
    make_modal_completion_call,
    make_modal_responses_call,
)

LlmCall = Callable[..., Awaitable[Any]]


async def send_modal_request(
    request_data: dict[str, Any],
    user: AuthenticatedUser,
    is_streaming: bool,
    product: str,
    provider_config: ProviderConfig,
    make_call: Callable[[str, str, str], LlmCall],
    settings: Settings | None = None,
    handle_request: LlmCall = handle_llm_request,
) -> dict[str, Any] | StreamingResponse:
    model = request_data["model"]
    ensure_modal_model_allowed(model)
    api_base, modal_key, modal_secret = ensure_modal_model_configured(model, settings or get_settings())
    return await handle_request(
        request_data=dict(request_data),
        user=user,
        model=model,
        is_streaming=is_streaming,
        provider_config=provider_config,
        llm_call=make_call(api_base, modal_key, modal_secret),
        product=product,
    )


async def send_modal_anthropic_messages(
    request_data: dict[str, Any], user: AuthenticatedUser, is_streaming: bool, product: str
) -> dict[str, Any] | StreamingResponse:
    return await send_modal_request(
        drop_orphaned_clear_thinking(request_data, product=product),
        user,
        is_streaming,
        product,
        MODAL_ANTHROPIC_CONFIG,
        make_modal_anthropic_call,
    )


async def send_modal_chat_completions(
    request_data: dict[str, Any], user: AuthenticatedUser, is_streaming: bool, product: str
) -> dict[str, Any] | StreamingResponse:
    return await send_modal_request(
        request_data, user, is_streaming, product, MODAL_OPENAI_CONFIG, make_modal_completion_call
    )


async def send_modal_responses(
    request_data: dict[str, Any], user: AuthenticatedUser, is_streaming: bool, product: str
) -> dict[str, Any] | StreamingResponse:
    return await send_modal_request(
        request_data, user, is_streaming, product, MODAL_OPENAI_RESPONSES_CONFIG, make_modal_responses_call
    )
