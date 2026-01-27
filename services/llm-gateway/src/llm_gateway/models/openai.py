from typing import Any

from pydantic import BaseModel, ConfigDict


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[dict[str, Any]]
    stream: bool = False


class ResponsesRequest(BaseModel):
    """OpenAI Responses API request model.

    The Responses API is a newer stateful API from OpenAI that supports
    multimodal inputs, reasoning models, and persistent conversations.
    """

    model_config = ConfigDict(extra="allow")

    model: str
    input: str | list[dict[str, Any]]
    stream: bool = False
    max_output_tokens: int | None = None
    previous_response_id: str | None = None
