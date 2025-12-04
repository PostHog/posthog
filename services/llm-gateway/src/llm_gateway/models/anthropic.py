from typing import Any, Literal

from pydantic import BaseModel, Field


class AnthropicMessagesRequest(BaseModel):
    model: str = Field(..., description="Model to use (e.g., 'claude-3-5-sonnet-20241022')")
    messages: list[dict[str, Any]] = Field(..., description="List of message objects")
    max_tokens: int = Field(default=4096, ge=1)
    temperature: float | None = Field(default=None, ge=0.0, le=1.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=0)
    stream: bool = Field(default=False)
    stop_sequences: list[str] | None = None
    system: str | list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None
    thinking: dict[str, Any] | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: dict[str, Any] | None = None
    service_tier: Literal["auto", "standard_only"] | None = None


class AnthropicUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    server_tool_use: dict[str, Any] | None = None
    service_tier: Literal["standard", "priority", "batch"] | None = None


class AnthropicMessagesResponse(BaseModel):
    id: str
    type: Literal["message"]
    role: Literal["assistant"]
    content: list[dict[str, Any]]
    model: str
    stop_reason: Literal["end_turn", "max_tokens", "stop_sequence", "tool_use", "pause_turn", "refusal"] | None
    stop_sequence: str | None = None
    usage: AnthropicUsage
