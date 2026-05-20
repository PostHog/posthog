from collections.abc import Generator
from typing import Any, Protocol

from products.llm_analytics.backend.llm.types import (
    AnalyticsContext,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
)


class Provider(Protocol):
    """Protocol for LLM providers"""

    @property
    def name(self) -> str:
        """Provider name (e.g., 'openai', 'anthropic', 'gemini')"""
        ...

    def complete(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        base_url: str | None = None,
    ) -> CompletionResponse:
        """Non-streaming completion"""
        ...

    def stream(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        base_url: str | None = None,
    ) -> Generator[StreamChunk, None, None]:
        """Streaming completion"""
        ...

    @staticmethod
    def validate_key(api_key: str, **kwargs: Any) -> tuple[str, str | None]:
        """Validate an API key. Returns (state, error_message).

        `**kwargs` is provider-specific extra config — e.g. Azure OpenAI accepts
        ``azure_endpoint`` and ``api_version``. Most providers ignore kwargs.
        """
        ...

    @staticmethod
    def list_models(api_key: str | None = None, **kwargs: Any) -> list[str]:
        """List available models for this provider.

        `**kwargs` is provider-specific extra config (see ``validate_key``).
        """
        ...

    @staticmethod
    def recommended_models() -> set[str]:
        """Return the set of curated/recommended model IDs for this provider."""
        ...
