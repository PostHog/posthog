"""Azure OpenAI provider for unified LLM client.

Azure OpenAI uses deployment-based model naming and requires an azure_endpoint
and api_version in addition to an API key. This provider is BYOK-only.
"""

import logging
from typing import Any

import openai

from products.llm_analytics.backend.llm.providers.openai import OpenAIAdapter, OpenAIConfig
from products.llm_analytics.backend.llm.types import AnalyticsContext

logger = logging.getLogger(__name__)

DEFAULT_API_VERSION = "2024-10-21"


class AzureOpenAIAdapter(OpenAIAdapter):
    """Azure OpenAI provider that uses openai.AzureOpenAI for client construction."""

    name = "azure_openai"

    def __init__(self, azure_endpoint: str = "", api_version: str = DEFAULT_API_VERSION):
        self.azure_endpoint = azure_endpoint
        self.api_version = api_version or DEFAULT_API_VERSION

    def _create_client(
        self,
        api_key: str,
        base_url: str | None,
        analytics: AnalyticsContext,
    ) -> Any:
        """Create an AzureOpenAI client. Ignores base_url — uses azure_endpoint instead."""
        return openai.AzureOpenAI(
            api_key=api_key,
            azure_endpoint=self.azure_endpoint,
            api_version=self.api_version,
            timeout=OpenAIConfig.TIMEOUT,
        )

    @staticmethod
    def validate_key(api_key: str, **kwargs: Any) -> tuple[str, str | None]:
        """Validate an Azure OpenAI API key by listing models (deployments)."""
        from products.llm_analytics.backend.models.provider_keys import LLMProviderKey

        azure_endpoint = kwargs.get("azure_endpoint", "")
        api_version = kwargs.get("api_version", DEFAULT_API_VERSION)

        if not azure_endpoint:
            return (LLMProviderKey.State.INVALID, "Azure endpoint is required")

        try:
            client = openai.AzureOpenAI(
                api_key=api_key,
                azure_endpoint=azure_endpoint,
                api_version=api_version,
                timeout=OpenAIConfig.TIMEOUT,
            )
            client.models.list()
            return (LLMProviderKey.State.OK, None)
        except openai.AuthenticationError:
            return (LLMProviderKey.State.INVALID, "Invalid API key")
        except openai.APIConnectionError:
            return (LLMProviderKey.State.ERROR, "Could not connect to Azure OpenAI endpoint")
        except openai.RateLimitError:
            return (LLMProviderKey.State.ERROR, "Rate limited, please try again later")
        except Exception as e:
            logger.exception(f"Azure OpenAI key validation error: {e}")
            return (LLMProviderKey.State.ERROR, "Validation failed, please try again")

    @staticmethod
    def recommended_models() -> set[str]:
        return set()

    @staticmethod
    def list_models(api_key: str | None = None, **kwargs: Any) -> list[str]:
        """List available Azure OpenAI deployments. Returns empty list without a key (BYOK-only)."""
        if not api_key:
            return []

        azure_endpoint = kwargs.get("azure_endpoint", "")
        api_version = kwargs.get("api_version", DEFAULT_API_VERSION)

        if not azure_endpoint:
            return []

        try:
            client = openai.AzureOpenAI(
                api_key=api_key,
                azure_endpoint=azure_endpoint,
                api_version=api_version,
                timeout=OpenAIConfig.TIMEOUT,
            )
            return [m.id for m in sorted(client.models.list(), key=lambda m: m.created, reverse=True)]
        except Exception:
            logger.exception("Error listing Azure OpenAI models")
            return []

    @staticmethod
    def get_api_key() -> str:
        raise ValueError("Azure OpenAI is BYOKEY-only. No default API key is available.")

    def _get_default_api_key(self) -> str:
        raise ValueError("Azure OpenAI is BYOKEY-only. No default API key is available.")
