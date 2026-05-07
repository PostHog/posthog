"""Together AI provider for the unified LLM client.

Together exposes an OpenAI-compatible API and is BYOKEY-only.
"""

import logging
from collections.abc import Generator
from typing import Any

import httpx

from products.llm_analytics.backend.llm.providers.openai import OpenAIAdapter, OpenAIConfig
from products.llm_analytics.backend.llm.types import (
    AnalyticsContext,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
)

logger = logging.getLogger(__name__)

TOGETHER_BASE_URL = "https://api.together.xyz/v1"
TOGETHER_MODELS_URL = f"{TOGETHER_BASE_URL}/models"


def _get_models_response(api_key: str) -> httpx.Response:
    return httpx.get(
        TOGETHER_MODELS_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=OpenAIConfig.TIMEOUT,
    )


def _parse_models_response(response: httpx.Response) -> list[dict[str, object]]:
    data = response.json()
    if not isinstance(data, list):
        return []

    models: list[dict[str, object]] = []
    for item in data:
        if isinstance(item, dict):
            models.append({str(key): value for key, value in item.items()})
    return models


def _model_created(model: dict[str, object]) -> int:
    created = model.get("created")
    if isinstance(created, int):
        return created
    return 0


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
    def validate_key(api_key: str, **kwargs: Any) -> tuple[str, str | None]:
        """Validate a Together AI API key using a models list request."""
        from products.llm_analytics.backend.models.provider_keys import LLMProviderKey

        try:
            response = _get_models_response(api_key)

            if response.status_code == 200:
                return (LLMProviderKey.State.OK, None)

            if response.status_code == 401:
                return (LLMProviderKey.State.INVALID, "Invalid API key")

            if response.status_code == 429:
                return (LLMProviderKey.State.ERROR, "Rate limited, please try again later")

            return (LLMProviderKey.State.ERROR, f"Unexpected response status: {response.status_code}")
        except httpx.TimeoutException:
            return (LLMProviderKey.State.ERROR, "Request timed out, please try again")
        except httpx.ConnectError:
            return (LLMProviderKey.State.ERROR, "Could not connect to Together AI")
        except httpx.HTTPError:
            logger.exception("Together AI key validation HTTP error")
            return (LLMProviderKey.State.ERROR, "Could not connect to Together AI")
        except Exception:
            logger.exception("Together AI key validation error")
            return (LLMProviderKey.State.ERROR, "Validation failed, please try again")

    @staticmethod
    def recommended_models() -> set[str]:
        return set()

    @staticmethod
    def list_models(api_key: str | None = None, **kwargs: Any) -> list[str]:
        """List Together AI models. Returns empty without a key (BYOKEY-only)."""
        if not api_key:
            return []

        try:
            response = _get_models_response(api_key)
            if response.status_code == 401:
                return []
            if response.status_code == 429:
                logger.warning("Rate limited while listing Together AI models")
                return []
            response.raise_for_status()

            models = sorted(
                _parse_models_response(response),
                key=_model_created,
                reverse=True,
            )
            return [model_id for model in models if isinstance(model_id := model.get("id"), str)]
        except httpx.HTTPError:
            logger.exception("HTTP error listing Together AI models")
            return []
        except Exception:
            logger.exception("Error listing Together AI models")
            return []

    @staticmethod
    def get_api_key() -> str:
        raise ValueError("Together AI is BYOKEY-only. No default API key is available.")

    def _get_default_api_key(self) -> str:
        raise ValueError("Together AI is BYOKEY-only. No default API key is available.")
