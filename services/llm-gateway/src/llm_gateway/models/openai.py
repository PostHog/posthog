from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatCompletionRequest(BaseModel):
    model: str = Field(..., description="Model to use (e.g., 'gpt-4')")
    messages: list[dict[str, Any]] = Field(..., description="List of message objects")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    n: int | None = Field(default=None, ge=1)
    stream: bool = Field(default=False)
    stream_options: dict[str, Any] | None = None
    stop: list[str] | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    max_completion_tokens: int | None = Field(default=None, ge=1)
    presence_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    frequency_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    logit_bias: dict[str, Any] | None = None
    user: str | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None
    parallel_tool_calls: bool | None = None
    response_format: dict[str, Any] | None = None
    seed: int | None = None
    logprobs: bool | None = None
    top_logprobs: int | None = Field(default=None, ge=0, le=20)
    modalities: list[Literal["text", "audio"]] | None = None
    prediction: dict[str, Any] | None = None
    audio: dict[str, Any] | None = None
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "default"] | None = None
    verbosity: Literal["concise", "standard", "verbose"] | None = None
    store: bool | None = None
    web_search_options: dict[str, Any] | None = None
    functions: list[dict[str, Any]] | None = None
    function_call: dict[str, Any] | None = None


class ChatCompletionMessage(BaseModel):
    role: str
    content: str | None = None
    name: str | None = None
    function_call: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] | None = None


class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatCompletionMessage
    finish_reason: str | None


class ChatCompletionUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    completion_tokens_details: dict[str, Any] | None = None
    prompt_tokens_details: dict[str, Any] | None = None


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"]
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage | None = None
    system_fingerprint: str | None = None
    service_tier: Literal["auto", "default", "flex", "scale", "priority"] | None = None
