"""
Base provider transformer interface.

Provider transformers handle framework/library-specific OTEL formats
and normalize them to PostHog's standard format.

When adding a new provider transformer, document these aspects:
1. Detection method (scope name, attribute prefix, etc.)
2. OTEL pattern (v1 attributes-only vs v2 traces+logs)
3. Message format quirks (JSON wrapping, content arrays, etc.)
4. Conversation history behavior (accumulated vs per-call)
5. Any other notable behaviors

See mastra.py for an example of well-documented provider behavior.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any


class OtelInstrumentationPattern(Enum):
    """
    OTEL instrumentation patterns for LLM frameworks.

    V1_ATTRIBUTES: All data (metadata + content) in span attributes
        - Send events immediately, no waiting for logs
        - Example: opentelemetry-instrumentation-openai, Mastra

    V2_TRACES_AND_LOGS: Metadata in spans, content in separate log events
        - Requires event merger to combine traces + logs
        - Example: opentelemetry-instrumentation-openai-v2
    """

    V1_ATTRIBUTES = "v1_attributes"
    V2_TRACES_AND_LOGS = "v2_traces_and_logs"


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

    def get_instrumentation_pattern(self) -> OtelInstrumentationPattern:
        """
        Get the OTEL instrumentation pattern this provider uses.

        Override in subclass to declare the pattern. Default is V2_TRACES_AND_LOGS
        for safety - better to wait for logs than to send incomplete events.

        Returns:
            The instrumentation pattern enum value
        """
        return OtelInstrumentationPattern.V2_TRACES_AND_LOGS
