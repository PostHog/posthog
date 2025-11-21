"""
Base provider transformer interface.

Provider transformers handle framework/library-specific OTEL formats
and normalize them to PostHog's standard format.
"""

from abc import ABC, abstractmethod
from typing import Any


class ProviderTransformer(ABC):
    """
    Base class for provider-specific OTEL transformers.

    Each provider (Mastra, Langchain, LlamaIndex, etc.) can implement
    a transformer to handle their specific OTEL format quirks.
    """

    @abstractmethod
    def can_handle(self, span: dict[str, Any], scope: dict[str, Any]) -> bool:
        """
        Detect if this transformer can handle the given span.

        Args:
            span: Parsed OTEL span
            scope: Instrumentation scope info

        Returns:
            True if this transformer recognizes and can handle this span
        """
        pass

    @abstractmethod
    def transform_prompt(self, prompt: Any) -> Any:
        """
        Transform provider-specific prompt format to standard format.

        Args:
            prompt: Raw prompt value from gen_ai.prompt attribute

        Returns:
            Normalized prompt (list of message dicts, string, or None if no transformation needed)
        """
        pass

    @abstractmethod
    def transform_completion(self, completion: Any) -> Any:
        """
        Transform provider-specific completion format to standard format.

        Args:
            completion: Raw completion value from gen_ai.completion attribute

        Returns:
            Normalized completion (list of message dicts, string, or None if no transformation needed)
        """
        pass

    def get_provider_name(self) -> str:
        """
        Get the provider name for logging/debugging.

        Returns:
            Human-readable provider name
        """
        return self.__class__.__name__.replace("Transformer", "")
