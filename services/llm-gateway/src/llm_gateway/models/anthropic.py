from typing import Any

from pydantic import BaseModel, ConfigDict


class AnthropicMessagesRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[dict[str, Any]]
    max_tokens: int = 4096
    stream: bool = False
