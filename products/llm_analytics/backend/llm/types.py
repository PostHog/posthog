from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class CompletionRequest:
    """Request for LLM completion"""

    model: str
    messages: list[dict[str, Any]]
    provider: str
    system: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None
    response_format: type[BaseModel] | None = None
    thinking: bool = False
    reasoning_level: str | None = None


@dataclass
class CompletionResponse:
    """Response from non-streaming completion"""

    content: str
    model: str
    usage: Usage | None = None
    parsed: BaseModel | None = None


@dataclass
class StreamChunk:
    """Chunk from streaming completion (SSE format)"""

    type: Literal["text", "tool_call", "usage", "reasoning", "error"]
    data: dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> str:
        """Convert to SSE formatted string"""
        import json

        return f"data: {json.dumps({'type': self.type, **self.data})}\n\n"


@dataclass
class AnalyticsContext:
    """Context for PostHog analytics tracking"""

    distinct_id: str = ""
    trace_id: str | None = None
    properties: dict[str, Any] | None = None
    groups: dict[str, Any] | None = None
    capture: bool = True
