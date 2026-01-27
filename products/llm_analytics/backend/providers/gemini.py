"""
DEPRECATED: This module is internal to LLM Analytics and should not be imported by other products.

If you are importing this from outside llm_analytics, please either:
- Copy the code you need into your own codebase and maintain it there
- Migrate to the LLM Gateway when available

This shim will be removed in a future release.
"""

from collections.abc import Generator
from typing import Any

from products.llm_analytics.backend.llm.providers.gemini import GeminiAdapter, GeminiConfig
from products.llm_analytics.backend.llm.types import AnalyticsContext, CompletionRequest

__all__ = ["GeminiConfig", "GeminiProvider"]


class GeminiProvider:
    """Backward-compatible wrapper - delegates to GeminiAdapter."""

    def __init__(self, model_id: str, api_key: str | None = None):
        self._adapter = GeminiAdapter()
        self.model_id = model_id
        self._api_key = api_key

    @classmethod
    def get_api_key(cls) -> str:
        return GeminiAdapter.get_api_key()

    def validate_model(self, model_id: str) -> None:
        """Validate that the model is supported."""
        if model_id not in GeminiConfig.SUPPORTED_MODELS:
            raise ValueError(f"Model {model_id} is not supported. Supported models: {GeminiConfig.SUPPORTED_MODELS}")

    @staticmethod
    def prepare_config_kwargs(
        system: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Prepare Gemini config kwargs - delegates to adapter."""
        return GeminiAdapter._prepare_config_kwargs(system, temperature, max_tokens, tools)

    def stream_response(
        self,
        system: str,
        messages: list[dict[str, Any]],
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
            provider="gemini",
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

    def get_response(
        self,
        system: str,
        prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
        distinct_id: str = "",
        trace_id: str | None = None,
        properties: dict | None = None,
        groups: dict | None = None,
    ) -> str:
        """Get direct string response from Gemini API for a provided string prompt."""
        request = CompletionRequest(
            model=self.model_id,
            messages=[{"role": "user", "content": prompt}],
            provider="gemini",
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
        )
        analytics = AnalyticsContext(
            distinct_id=distinct_id,
            trace_id=trace_id,
            properties=properties,
            groups=groups,
        )
        response = self._adapter.complete(request, self._api_key, analytics)
        return response.content
