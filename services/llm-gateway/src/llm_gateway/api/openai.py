from typing import Annotated, Any

import litellm
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from llm_gateway.api.handler import (
    OPENAI_CONFIG,
    OPENAI_RESPONSES_CONFIG,
    OPENAI_TRANSCRIPTION_CONFIG,
    handle_llm_request,
)
from llm_gateway.dependencies import RateLimitedUser
from llm_gateway.models.openai import ChatCompletionRequest, ResponsesRequest, TranscriptionRequest
from llm_gateway.products.config import validate_product

openai_router = APIRouter()


def _normalize_model_name(model: str) -> str:
    """Ensure model name has openai/ prefix for litellm routing."""
    if model.startswith("openai/"):
        return model
    return f"openai/{model}"


async def _handle_chat_completions(
    body: ChatCompletionRequest,
    user: RateLimitedUser,
    product: str = "llm_gateway",
) -> dict[str, Any] | StreamingResponse:
    data = body.model_dump(exclude_none=True)

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

    original_model = body.model
    normalized_model = _normalize_model_name(original_model)
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
) -> dict[str, Any] | StreamingResponse:
    return await _handle_chat_completions(body, user)


@openai_router.post("/{product}/v1/chat/completions", response_model=None)
async def chat_completions_with_product(
    body: ChatCompletionRequest,
    user: RateLimitedUser,
    product: str,
) -> dict[str, Any] | StreamingResponse:
    validate_product(product)
    return await _handle_chat_completions(body, user, product=product)


@openai_router.post("/v1/responses", response_model=None)
async def responses_v1(
    body: ResponsesRequest,
    user: RateLimitedUser,
) -> dict[str, Any] | StreamingResponse:
    return await _handle_responses(body, user)


@openai_router.post("/{product}/v1/responses", response_model=None)
async def responses_v1_with_product(
    body: ResponsesRequest,
    user: RateLimitedUser,
    product: str,
) -> dict[str, Any] | StreamingResponse:
    validate_product(product)
    return await _handle_responses(body, user, product=product)


@openai_router.post("/responses", response_model=None)
async def responses(
    body: ResponsesRequest,
    user: RateLimitedUser,
) -> dict[str, Any] | StreamingResponse:
    return await _handle_responses(body, user)


@openai_router.post("/{product}/responses", response_model=None)
async def responses_with_product(
    body: ResponsesRequest,
    user: RateLimitedUser,
    product: str,
) -> dict[str, Any] | StreamingResponse:
    validate_product(product)
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

    normalized_model = _normalize_model_name(model)
    content = await file.read()
    file_tuple = (file.filename, content, file.content_type or "audio/mpeg")

    request = TranscriptionRequest(model=normalized_model, file=file_tuple, language=language)

    return await handle_llm_request(
        request_data=request.model_dump(exclude_none=True),
        user=user,
        model=normalized_model,
        is_streaming=False,
        provider_config=OPENAI_TRANSCRIPTION_CONFIG,
        llm_call=litellm.atranscription,
        product=product,
    )


@openai_router.post("/v1/audio/transcriptions", response_model=None)
async def audio_transcriptions(
    user: RateLimitedUser,
    file: Annotated[UploadFile, File()],
    model: Annotated[str, Form()] = "gpt-4o-transcribe",
    language: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    return await _handle_transcription(file, model, user, language)


@openai_router.post("/{product}/v1/audio/transcriptions", response_model=None)
async def audio_transcriptions_with_product(
    user: RateLimitedUser,
    product: str,
    file: Annotated[UploadFile, File()],
    model: Annotated[str, Form()] = "gpt-4o-transcribe",
    language: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    validate_product(product)
    return await _handle_transcription(file, model, user, language, product=product)
