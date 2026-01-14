"""
DEPRECATED: This module is internal to LLM Analytics and should not be imported by other products.

If you are importing this from outside llm_analytics, please either:
- Copy the code you need into your own codebase and maintain it there
- Migrate to the LLM Gateway when available

This shim will be removed in a future release.
"""

from collections.abc import Generator

from anthropic.types import MessageParam

from products.llm_analytics.backend.llm.providers.anthropic import AnthropicAdapter, AnthropicConfig
from products.llm_analytics.backend.llm.types import AnalyticsContext, CompletionRequest

__all__ = ["AnthropicConfig", "AnthropicProvider"]


class AnthropicProvider:
    """Backward-compatible wrapper - delegates to AnthropicAdapter."""

    def __init__(self, model_id: str, api_key: str | None = None):
        self._adapter = AnthropicAdapter()
        self.model_id = model_id
        self._api_key = api_key

    @classmethod
    def get_api_key(cls) -> str:
        return AnthropicAdapter.get_api_key()

    def stream_response(
        self,
        system: str,
        messages: list[MessageParam],
        thinking: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
        distinct_id: str = "",
        trace_id: str | None = None,
        properties: dict | None = None,
        groups: dict | None = None,
    ) -> Generator[str, None]:
        """Generator function that yields SSE formatted data."""
        request = CompletionRequest(
            model=self.model_id,
            messages=list(messages),
            provider="anthropic",
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            thinking=thinking,
        )
        analytics = AnalyticsContext(
            distinct_id=distinct_id,
            trace_id=trace_id,
            properties=properties,
            groups=groups,
        )
        for chunk in self._adapter.stream(request, self._api_key, analytics):
            yield chunk.to_sse()
