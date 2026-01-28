from collections.abc import Generator
from typing import Protocol

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
    ) -> CompletionResponse:
        """Non-streaming completion"""
        ...

    def stream(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
    ) -> Generator[StreamChunk, None, None]:
        """Streaming completion"""
        ...

    @staticmethod
    def validate_key(api_key: str) -> tuple[str, str | None]:
        """Validate an API key. Returns (state, error_message)."""
        ...

    @staticmethod
    def list_models(api_key: str | None = None) -> list[str]:
        """List available models for this provider"""
        ...
