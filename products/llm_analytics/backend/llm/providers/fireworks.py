"""Fireworks provider for unified LLM client.

Fireworks provides an OpenAI-compatible API and is BYOKEY-only.
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

FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"


class FireworksAdapter(OpenAIAdapter):
    """Fireworks provider that reuses OpenAI's completion/streaming logic."""

    name = "fireworks"

    def complete(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        base_url: str | None = None,
    ) -> CompletionResponse:
        return super().complete(request, api_key, analytics, base_url=FIREWORKS_BASE_URL)

    def stream(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        base_url: str | None = None,
    ) -> Generator[StreamChunk, None, None]:
        yield from super().stream(request, api_key, analytics, base_url=FIREWORKS_BASE_URL)

    @staticmethod
    def validate_key(api_key: str) -> tuple[str, str | None]:
        """Validate a Fireworks API key using a models list request."""
        from products.llm_analytics.backend.models.provider_keys import LLMProviderKey

        try:
            client = openai.OpenAI(
                api_key=api_key,
                base_url=FIREWORKS_BASE_URL,
                timeout=OpenAIConfig.TIMEOUT,
            )
            client.models.list()
            return (LLMProviderKey.State.OK, None)
        except openai.AuthenticationError:
            return (LLMProviderKey.State.INVALID, "Invalid API key")
        except openai.RateLimitError:
            return (LLMProviderKey.State.ERROR, "Rate limited, please try again later")
        except openai.APIConnectionError:
            return (LLMProviderKey.State.ERROR, "Could not connect to Fireworks")
        except Exception:
            logger.exception("Fireworks key validation error")
            return (LLMProviderKey.State.ERROR, "Validation failed, please try again")

    @staticmethod
    def list_models(api_key: str | None = None) -> list[str]:
        """List available Fireworks models. Returns empty list without a key (BYOKEY-only)."""
        if not api_key:
            return []

        try:
            client = openai.OpenAI(
                api_key=api_key,
                base_url=FIREWORKS_BASE_URL,
                timeout=OpenAIConfig.TIMEOUT,
            )
            return sorted(m.id for m in client.models.list())
        except Exception:
            logger.exception("Error listing Fireworks models")
            return []

    @staticmethod
    def get_api_key() -> str:
        raise ValueError("Fireworks is BYOKEY-only. No default API key is available.")

    def _get_default_api_key(self) -> str:
        raise ValueError("Fireworks is BYOKEY-only. No default API key is available.")
