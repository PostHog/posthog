"""Together AI provider for the unified LLM client.

Together exposes an OpenAI-compatible API and is BYOKEY-only.
"""

import logging
from collections.abc import Generator

import openai

from products.llm_analytics.backend.llm.providers.openai import OpenAIAdapter, OpenAIConfig
from products.llm_analytics.backend.llm.types import (
    AnalyticsContext,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
)

logger = logging.getLogger(__name__)

TOGETHER_BASE_URL = "https://api.together.xyz/v1"


class TogetherAdapter(OpenAIAdapter):
    """Together AI provider that reuses OpenAI's completion/streaming logic."""

    name = "together_ai"

    def complete(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        base_url: str | None = None,
    ) -> CompletionResponse:
        return super().complete(request, api_key, analytics, base_url=TOGETHER_BASE_URL)

    def stream(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        base_url: str | None = None,
    ) -> Generator[StreamChunk, None, None]:
        yield from super().stream(request, api_key, analytics, base_url=TOGETHER_BASE_URL)

    @staticmethod
    def validate_key(api_key: str) -> tuple[str, str | None]:
        """Validate a Together AI API key using a models list request."""
        from products.llm_analytics.backend.models.provider_keys import LLMProviderKey

        try:
            client = openai.OpenAI(
                api_key=api_key,
                base_url=TOGETHER_BASE_URL,
                timeout=OpenAIConfig.TIMEOUT,
            )
            client.models.list()
            return (LLMProviderKey.State.OK, None)
        except openai.AuthenticationError:
            return (LLMProviderKey.State.INVALID, "Invalid API key")
        except openai.RateLimitError:
            return (LLMProviderKey.State.ERROR, "Rate limited, please try again later")
        except openai.APIConnectionError:
            return (LLMProviderKey.State.ERROR, "Could not connect to Together AI")
        except Exception:
            logger.exception("Together AI key validation error")
            return (LLMProviderKey.State.ERROR, "Validation failed, please try again")

    @staticmethod
    def recommended_models() -> set[str]:
        return set()

    @staticmethod
    def list_models(api_key: str | None = None) -> list[str]:
        """List Together AI models. Returns empty without a key (BYOKEY-only)."""
        if not api_key:
            return []

        try:
            client = openai.OpenAI(
                api_key=api_key,
                base_url=TOGETHER_BASE_URL,
                timeout=OpenAIConfig.TIMEOUT,
            )
            models = sorted(
                client.models.list(),
                key=lambda model: model.created,
                reverse=True,
            )
            return [model.id for model in models]
        except Exception:
            logger.exception("Error listing Together AI models")
            return []

    @staticmethod
    def get_api_key() -> str:
        raise ValueError("Together AI is BYOKEY-only. No default API key is available.")

    def _get_default_api_key(self) -> str:
        raise ValueError("Together AI is BYOKEY-only. No default API key is available.")
