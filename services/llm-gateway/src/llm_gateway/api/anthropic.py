from typing import Any

import litellm
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from llm_gateway.api.handler import ANTHROPIC_CONFIG, handle_llm_request
from llm_gateway.dependencies import RateLimitedUser
from llm_gateway.models.anthropic import AnthropicMessagesRequest

anthropic_router = APIRouter()


@anthropic_router.post("/v1/messages", response_model=None)
async def anthropic_messages(
    request: AnthropicMessagesRequest,
    user: RateLimitedUser,
) -> dict[str, Any] | StreamingResponse:
    data = request.model_dump(exclude_none=True)

    return await handle_llm_request(
        request_data=data,
        user=user,
        model=request.model,
        is_streaming=request.stream or False,
        provider_config=ANTHROPIC_CONFIG,
        llm_call=litellm.anthropic_messages,
    )
