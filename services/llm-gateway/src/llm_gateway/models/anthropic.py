from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

GATEWAY_ONLY_FIELDS = {"provider", "use_bedrock_fallback"}


class AnthropicMessagesRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[dict[str, Any]]
    max_tokens: int = 4096
    stream: bool = False
    provider: Literal["anthropic", "bedrock"] | None = None
    use_bedrock_fallback: bool = False


class AnthropicCountTokensRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[dict[str, Any]]
    provider: Literal["anthropic", "bedrock"] | None = None
    use_bedrock_fallback: bool = False
