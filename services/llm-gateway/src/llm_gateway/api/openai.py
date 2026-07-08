from typing import Annotated, Any, cast

import litellm
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from llm_gateway.api.handler import (
    CLOUDFLARE_OPENAI_CONFIG,
    CLOUDFLARE_OPENAI_RESPONSES_CONFIG,
    OPENAI_CONFIG,
    OPENAI_RESPONSES_CONFIG,
    OPENAI_TRANSCRIPTION_CONFIG,
    handle_llm_request,
    normalize_litellm_model_name,
)
from llm_gateway.cloudflare import (
    ensure_cloudflare_configured,
    ensure_cloudflare_model_allowed,
    is_cloudflare_model,
    make_cloudflare_completion_call,
    make_cloudflare_responses_call,
)
from llm_gateway.config import get_settings
from llm_gateway.dependencies import RateLimitedUser
from llm_gateway.models.openai import ChatCompletionRequest, ResponsesRequest, TranscriptionRequest
from llm_gateway.products.config import validate_product
from llm_gateway.request_context import apply_posthog_context_from_headers

openai_router = APIRouter()


def _invalid_request_error(message: str) -> HTTPException:
    """A 400 in the OpenAI error envelope (mirrors anthropic.py's `_invalid_header_exception`)."""
    return HTTPException(
        status_code=400,
        detail={"error": {"message": message, "type": "invalid_request_error", "code": None}},
    )


async def _handle_chat_completions(
    body: ChatCompletionRequest,
    user: RateLimitedUser,
    product: str = "llm_gateway",
) -> dict[str, Any] | StreamingResponse:
    data = body.model_dump(exclude_none=True)

    if is_cloudflare_model(body.model):
        ensure_cloudflare_model_allowed(body.model)
        settings = get_settings()
        api_base, api_key = ensure_cloudflare_configured(settings)
        return await handle_llm_request(
            request_data=data,
            user=user,
            model=body.model,
            is_streaming=body.stream or False,
            provider_config=CLOUDFLARE_OPENAI_CONFIG,
            llm_call=make_cloudflare_completion_call(api_base, api_key),
            product=product,
        )

    return await handle_llm_request(
        request_data=data,
        user=user,
        model=body.model,
        is_streaming=body.stream or False,
        provider_config=OPENAI_CONFIG,
        llm_call=litellm.acompletion,
        product=product,
    )


async def _handle_responses(
    body: ResponsesRequest,
    user: RateLimitedUser,
    product: str = "llm_gateway",
) -> dict[str, Any] | StreamingResponse:
    """Handle OpenAI Responses API request.

    The Responses API is used by Codex and other agentic applications.
    It supports multimodal inputs, reasoning models, and persistent conversations.
    """
    data = body.model_dump(exclude_none=True)

    if is_cloudflare_model(body.model):
        # CF-served models (`@cf/...`) can't use the native OpenAI Responses path below: it would
        # prefix `openai/` and call the real OpenAI Responses API. Route through CF's endpoint via
        # litellm's Responses->chat/completions bridge instead (see make_cloudflare_responses_call).
        if body.previous_response_id is not None:
            # The bridge rebuilds prior turns from litellm proxy spend logs; we run litellm as an
            # SDK (no proxy DB), so it would silently resolve to empty history and drop the
            # conversation. Reject explicitly rather than answer with lost context.
            raise _invalid_request_error(
                "previous_response_id is not supported for Cloudflare models on the Responses API"
            )
        if data.get("tools"):
            # `tools` arrives as an extra field (ResponsesRequest allows extras). The
            # Responses->chat/completions bridge doesn't faithfully translate Responses-shaped
            # tools: Responses-only types (`shell`, `custom`) pass through unchanged and
            # chat-completions-shaped function tools lose their name, so CF's chat/completions
            # endpoint rejects the payload. Reject up front rather than hand CF a request that
            # will fail once tools are advertised.
            raise _invalid_request_error("tools are not yet supported for Cloudflare models on the Responses API")
        ensure_cloudflare_model_allowed(body.model)
        settings = get_settings()
        api_base, api_key = ensure_cloudflare_configured(settings)
        return await handle_llm_request(
            request_data=data,
            user=user,
            model=body.model,
            is_streaming=body.stream or False,
            provider_config=CLOUDFLARE_OPENAI_RESPONSES_CONFIG,
            llm_call=make_cloudflare_responses_call(api_base, api_key),
            product=product,
        )

    original_model = body.model
    normalized_model = normalize_litellm_model_name(original_model, OPENAI_RESPONSES_CONFIG.name)
    data["model"] = normalized_model

    return await handle_llm_request(
        request_data=data,
        user=user,
        model=normalized_model,
        is_streaming=body.stream or False,
        provider_config=OPENAI_RESPONSES_CONFIG,
        llm_call=litellm.aresponses,
        product=product,
    )


@openai_router.post("/v1/chat/completions", response_model=None)
async def chat_completions(
    body: ChatCompletionRequest,
    user: RateLimitedUser,
    request: Request,
) -> dict[str, Any] | StreamingResponse:
    apply_posthog_context_from_headers(request)
    return await _handle_chat_completions(body, user)


@openai_router.post("/{product}/v1/chat/completions", response_model=None)
async def chat_completions_with_product(
    body: ChatCompletionRequest,
    user: RateLimitedUser,
    product: str,
    request: Request,
) -> dict[str, Any] | StreamingResponse:
    validate_product(product)
    apply_posthog_context_from_headers(request)
    return await _handle_chat_completions(body, user, product=product)


@openai_router.post("/v1/responses", response_model=None)
async def responses_v1(
    body: ResponsesRequest,
    user: RateLimitedUser,
    request: Request,
) -> dict[str, Any] | StreamingResponse:
    apply_posthog_context_from_headers(request)
    return await _handle_responses(body, user)


@openai_router.post("/{product}/v1/responses", response_model=None)
async def responses_v1_with_product(
    body: ResponsesRequest,
    user: RateLimitedUser,
    product: str,
    request: Request,
) -> dict[str, Any] | StreamingResponse:
    validate_product(product)
    apply_posthog_context_from_headers(request)
    return await _handle_responses(body, user, product=product)


@openai_router.post("/responses", response_model=None)
async def responses(
    body: ResponsesRequest,
    user: RateLimitedUser,
    request: Request,
) -> dict[str, Any] | StreamingResponse:
    apply_posthog_context_from_headers(request)
    return await _handle_responses(body, user)


@openai_router.post("/{product}/responses", response_model=None)
async def responses_with_product(
    body: ResponsesRequest,
    user: RateLimitedUser,
    product: str,
    request: Request,
) -> dict[str, Any] | StreamingResponse:
    validate_product(product)
    apply_posthog_context_from_headers(request)
    return await _handle_responses(body, user, product=product)


async def _handle_transcription(
    file: UploadFile,
    model: str,
    user: RateLimitedUser,
    language: str | None = None,
    product: str = "llm_gateway",
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": "File must have a filename", "type": "invalid_request_error", "code": None}},
        )

    if file.size and file.size > 25 * 1024 * 1024:  # 25MB - OpenAI's limit
        raise HTTPException(
            status_code=413,
            detail={
                "error": {
                    "message": "File size exceeds maximum allowed size of 25MB",
                    "type": "invalid_request_error",
                    "code": None,
                }
            },
        )

    normalized_model = normalize_litellm_model_name(model, OPENAI_TRANSCRIPTION_CONFIG.name)
    content = await file.read()
    file_tuple = (file.filename, content, file.content_type or "audio/mpeg")

    request = TranscriptionRequest(model=normalized_model, file=file_tuple, language=language)

    # is_streaming=False always yields a dict, never a StreamingResponse.
    return cast(
        dict[str, Any],
        await handle_llm_request(
            request_data=request.model_dump(exclude_none=True),
            user=user,
            model=normalized_model,
            is_streaming=False,
            provider_config=OPENAI_TRANSCRIPTION_CONFIG,
            llm_call=litellm.atranscription,
            product=product,
        ),
    )


@openai_router.post("/v1/audio/transcriptions", response_model=None)
async def audio_transcriptions(
    user: RateLimitedUser,
    request: Request,
    file: Annotated[UploadFile, File()],
    model: Annotated[str, Form()] = "gpt-4o-transcribe",
    language: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    apply_posthog_context_from_headers(request)
    return await _handle_transcription(file, model, user, language)


@openai_router.post("/{product}/v1/audio/transcriptions", response_model=None)
async def audio_transcriptions_with_product(
    user: RateLimitedUser,
    product: str,
    request: Request,
    file: Annotated[UploadFile, File()],
    model: Annotated[str, Form()] = "gpt-4o-transcribe",
    language: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    validate_product(product)
    apply_posthog_context_from_headers(request)
    return await _handle_transcription(file, model, user, language, product=product)
