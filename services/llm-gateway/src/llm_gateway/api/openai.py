from typing import Any

import litellm
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from llm_gateway.api.handler import OPENAI_CONFIG, handle_llm_request
from llm_gateway.dependencies import RateLimitedUser
from llm_gateway.models.openai import ChatCompletionRequest

openai_router = APIRouter()


@openai_router.post("/v1/chat/completions", response_model=None)
async def chat_completions(
    request: ChatCompletionRequest,
    user: RateLimitedUser,
) -> dict[str, Any] | StreamingResponse:
    data = request.model_dump(exclude_none=True)

    return await handle_llm_request(
        request_data=data,
        user=user,
        model=request.model,
        is_streaming=request.stream or False,
        provider_config=OPENAI_CONFIG,
        llm_call=litellm.acompletion,
    )
