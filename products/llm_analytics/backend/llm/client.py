"""
Unified LLM client for llm_analytics.

Provides a single entry point for all LLMA-internal LLM API calls.
"""

import uuid
from collections.abc import Generator
from typing import TYPE_CHECKING

from products.llm_analytics.backend.llm.errors import ProviderMismatchError, UnsupportedProviderError
from products.llm_analytics.backend.llm.types import (
    AnalyticsContext,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
)

if TYPE_CHECKING:
    from products.llm_analytics.backend.llm.providers.base import Provider
    from products.llm_analytics.backend.models.provider_keys import LLMProviderKey


class Client:
    """Unified LLM client for llm_analytics."""

    def __init__(
        self,
        provider_key: "LLMProviderKey | None" = None,
        distinct_id: str = "",
        trace_id: str | None = None,
        properties: dict | None = None,
        groups: dict | None = None,
        capture_analytics: bool = True,
    ):
        self.provider_key = provider_key
        self.analytics = AnalyticsContext(
            distinct_id=distinct_id,
            trace_id=trace_id or str(uuid.uuid4()),
            properties=properties,
            groups=groups,
            capture=capture_analytics,
        )

    def _get_api_key(self) -> str | None:
        """Extract API key from provider key if set."""
        if self.provider_key is None:
            return None
        return self.provider_key.encrypted_config.get("api_key")

    def _validate_provider(self, request_provider: str) -> None:
        """Validate that request provider matches provider key's provider."""
        if self.provider_key is not None and self.provider_key.provider != request_provider:
            raise ProviderMismatchError(self.provider_key.provider, request_provider)

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Non-streaming completion."""
        self._validate_provider(request.provider)
        provider = _get_provider(request.provider)
        return provider.complete(request, self._get_api_key(), self.analytics)

    def stream(self, request: CompletionRequest) -> Generator[StreamChunk, None, None]:
        """Streaming completion."""
        self._validate_provider(request.provider)
        provider = _get_provider(request.provider)
        yield from provider.stream(request, self._get_api_key(), self.analytics)

    @classmethod
    def validate_key(cls, provider: str, api_key: str) -> tuple[str, str | None]:
        """Validate an API key for a provider. Returns (state, error_message)."""
        return _get_provider(provider).validate_key(api_key)

    @classmethod
    def list_models(cls, provider: str, api_key: str | None = None) -> list[str]:
        """List available models for a provider."""
        return _get_provider(provider).list_models(api_key)


def _get_provider(name: str) -> "Provider":
    """Get provider by name."""
    from products.llm_analytics.backend.llm.providers.anthropic import AnthropicAdapter
    from products.llm_analytics.backend.llm.providers.gemini import GeminiAdapter
    from products.llm_analytics.backend.llm.providers.openai import OpenAIAdapter

    match name:
        case "openai":
            return OpenAIAdapter()
        case "anthropic":
            return AnthropicAdapter()
        case "gemini":
            return GeminiAdapter()
        case _:
            raise UnsupportedProviderError(name)
