"""MiniMax provider for unified LLM client.

MiniMax provides an OpenAI-compatible API and is BYOKEY-only.
"""

import logging
from collections.abc import Generator
from typing import Any

import openai

from products.llm_analytics.backend.llm.providers.openai import OpenAIAdapter, OpenAIConfig
from products.llm_analytics.backend.llm.types import (
    AnalyticsContext,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
)

logger = logging.getLogger(__name__)

MINIMAX_BASE_URL = "https://api.minimax.io/v1"

MINIMAX_MODELS = [
    "MiniMax-M2.7",
    "MiniMax-M2.7-highspeed",
]


class MiniMaxAdapter(OpenAIAdapter):
    """MiniMax provider that reuses OpenAI's completion/streaming logic."""

    name = "minimax"

    def complete(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        base_url: str | None = None,
    ) -> CompletionResponse:
        return super().complete(request, api_key, analytics, base_url=MINIMAX_BASE_URL)

    def stream(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        base_url: str | None = None,
    ) -> Generator[StreamChunk, None, None]:
        yield from super().stream(request, api_key, analytics, base_url=MINIMAX_BASE_URL)

    @staticmethod
    def validate_key(api_key: str, **kwargs: Any) -> tuple[str, str | None]:
        """Validate a MiniMax API key using a lightweight models list request."""
        from products.llm_analytics.backend.models.provider_keys import LLMProviderKey

        try:
            client = openai.OpenAI(
                api_key=api_key,
                base_url=MINIMAX_BASE_URL,
                timeout=OpenAIConfig.TIMEOUT,
            )
            client.models.list()
            return (LLMProviderKey.State.OK, None)
        except openai.AuthenticationError:
            return (LLMProviderKey.State.INVALID, "Invalid API key")
        except openai.RateLimitError:
            return (LLMProviderKey.State.ERROR, "Rate limited, please try again later")
        except openai.APIConnectionError:
            return (LLMProviderKey.State.ERROR, "Could not connect to MiniMax")
        except Exception:
            logger.exception("MiniMax key validation error")
            return (LLMProviderKey.State.ERROR, "Validation failed, please try again")

    @staticmethod
    def recommended_models() -> set[str]:
        return set(MINIMAX_MODELS)

    @staticmethod
    def list_models(api_key: str | None = None, **kwargs: Any) -> list[str]:
        """List available MiniMax models.

        Without a key, returns the curated MINIMAX_MODELS list.
        With a key, returns MINIMAX_MODELS first, then any additional models from the API.
        """
        if not api_key:
            return list(MINIMAX_MODELS)

        supported = set(MINIMAX_MODELS)
        try:
            client = openai.OpenAI(
                api_key=api_key,
                base_url=MINIMAX_BASE_URL,
                timeout=OpenAIConfig.TIMEOUT,
            )
            api_models = client.models.list()
            other = [m.id for m in sorted(api_models, key=lambda m: m.created, reverse=True) if m.id not in supported]
            return list(MINIMAX_MODELS) + other
        except Exception:
            logger.exception("Error listing MiniMax models")
            return list(MINIMAX_MODELS)

    @staticmethod
    def get_api_key() -> str:
        raise ValueError("MiniMax is BYOKEY-only. No default API key is available.")

    def _get_default_api_key(self) -> str:
        raise ValueError("MiniMax is BYOKEY-only. No default API key is available.")
