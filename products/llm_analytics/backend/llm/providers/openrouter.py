"""OpenRouter provider for unified LLM client.

OpenRouter is an LLM gateway with an OpenAI-compatible API that exposes models
from many providers. It is BYOKEY-only (no PostHog trial key).
"""

import logging
from collections.abc import Generator

import httpx
import openai

from products.llm_analytics.backend.llm.providers.openai import OpenAIAdapter, OpenAIConfig
from products.llm_analytics.backend.llm.types import (
    AnalyticsContext,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
)

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# For App Attribution
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://posthog.com",
    "X-Title": "PostHog",
}


class OpenRouterAdapter(OpenAIAdapter):
    """OpenRouter provider that reuses OpenAI's completion/streaming logic."""

    name = "openrouter"

    def _get_default_headers(self) -> dict[str, str]:
        return OPENROUTER_HEADERS

    def complete(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        base_url: str | None = None,
    ) -> CompletionResponse:
        return super().complete(request, api_key, analytics, base_url=OPENROUTER_BASE_URL)

    def stream(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        base_url: str | None = None,
    ) -> Generator[StreamChunk, None, None]:
        yield from super().stream(request, api_key, analytics, base_url=OPENROUTER_BASE_URL)

    @staticmethod
    def validate_key(api_key: str) -> tuple[str, str | None]:
        """Validate an OpenRouter API key using the auth/key endpoint."""
        from products.llm_analytics.backend.models.provider_keys import LLMProviderKey

        try:
            response = httpx.get(
                "https://openrouter.ai/api/v1/auth/key",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=OpenAIConfig.TIMEOUT,
            )

            if response.status_code == 200:
                return (LLMProviderKey.State.OK, None)

            if response.status_code == 401:
                return (LLMProviderKey.State.INVALID, "Invalid API key")

            return (LLMProviderKey.State.ERROR, f"Unexpected response status: {response.status_code}")

        except httpx.TimeoutException:
            return (LLMProviderKey.State.ERROR, "Request timed out, please try again")
        except httpx.ConnectError:
            return (LLMProviderKey.State.ERROR, "Could not connect to OpenRouter")
        except Exception as e:
            logger.exception(f"OpenRouter key validation error: {e}")
            return (LLMProviderKey.State.ERROR, "Validation failed, please try again")

    @staticmethod
    def list_models(api_key: str | None = None) -> list[str]:
        """List available OpenRouter models. Returns empty list without a key (BYOKEY-only)."""
        if not api_key:
            return []

        try:
            client = openai.OpenAI(
                api_key=api_key,
                base_url=OPENROUTER_BASE_URL,
                timeout=OpenAIConfig.TIMEOUT,
                default_headers=OPENROUTER_HEADERS,
            )
            return sorted(m.id for m in client.models.list())
        except Exception as e:
            logger.exception(f"Error listing OpenRouter models: {e}")
            return []

    @staticmethod
    def get_api_key() -> str:
        raise ValueError("OpenRouter is BYOKEY-only. No default API key is available.")

    def _get_default_api_key(self) -> str:
        raise ValueError("OpenRouter is BYOKEY-only. No default API key is available.")
