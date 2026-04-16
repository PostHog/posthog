"""Azure OpenAI provider for unified LLM client.

Azure OpenAI uses deployment-based model naming and requires an azure_endpoint
and api_version in addition to an API key. This provider is BYOK-only.
"""

import logging
from typing import Any

import httpx
import openai
import posthoganalytics
from posthoganalytics.ai.openai import AzureOpenAI as WrappedAzureOpenAI

from products.llm_analytics.backend.llm.providers.openai import OpenAIAdapter, OpenAIConfig
from products.llm_analytics.backend.llm.types import AnalyticsContext

logger = logging.getLogger(__name__)

# Keep in sync with frontend DEFAULT_AZURE_API_VERSION in llmProviderKeysLogic.ts.
# Used for inference (chat completions).
DEFAULT_API_VERSION = "2024-10-21"

# GA data-plane versions like 2024-10-21 are inference-only and 404 on /openai/deployments.
# The deployments listing requires an authoring/preview version — pinned separately from the
# user-configured api_version so changing the inference version doesn't break validation.
DEPLOYMENTS_LIST_API_VERSION = "2023-03-15-preview"

# Listing is a cheap call; don't inherit the long completion timeout.
AZURE_LIST_TIMEOUT = 10.0


def _list_azure_deployments(api_key: str, azure_endpoint: str) -> list[str]:
    """List Azure OpenAI deployments.

    The openai SDK's `client.models.list()` returns the Azure model *catalog*,
    not the user-created deployments. Chat completions require a deployment
    name, so we hit the data-plane `/openai/deployments` endpoint directly.
    """
    endpoint = azure_endpoint.rstrip("/")
    url = f"{endpoint}/openai/deployments"

    response = httpx.get(
        url,
        params={"api-version": DEPLOYMENTS_LIST_API_VERSION},
        headers={"api-key": api_key},
        timeout=AZURE_LIST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json().get("data", [])
    data.sort(key=lambda d: (d.get("created_at") or 0, d.get("id") or ""), reverse=True)
    return [d["id"] for d in data if "id" in d]


class AzureOpenAIAdapter(OpenAIAdapter):
    """Azure OpenAI provider that uses openai.AzureOpenAI for client construction.

    Note on the kwargs / instance-attr split: static methods (`validate_key`,
    `list_models`) take ``azure_endpoint`` / ``api_version`` via ``**kwargs``
    because they run *before* an ``LLMProviderKey`` exists on disk (pre-save
    validation, pre-validation viewset). The instance method ``_create_client``
    reads from ``self`` because by the time it runs the adapter has been built
    from a persisted ``LLMProviderKey.encrypted_config``.
    """

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
        posthog_client = posthoganalytics.default_client
        if analytics.capture and posthog_client:
            return WrappedAzureOpenAI(
                posthog_client=posthog_client,
                api_key=api_key,
                azure_endpoint=self.azure_endpoint,
                api_version=self.api_version,
                timeout=OpenAIConfig.TIMEOUT,
            )
        return openai.AzureOpenAI(
            api_key=api_key,
            azure_endpoint=self.azure_endpoint,
            api_version=self.api_version,
            timeout=OpenAIConfig.TIMEOUT,
        )

    @staticmethod
    def validate_key(api_key: str, **kwargs: Any) -> tuple[str, str | None]:
        """Validate an Azure OpenAI API key by listing deployments."""
        from products.llm_analytics.backend.models.provider_keys import LLMProviderKey

        azure_endpoint = kwargs.get("azure_endpoint", "")

        if not azure_endpoint:
            return (LLMProviderKey.State.INVALID, "Azure endpoint is required")

        try:
            _list_azure_deployments(api_key, azure_endpoint)
            return (LLMProviderKey.State.OK, None)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                return (LLMProviderKey.State.INVALID, "Invalid API key")
            if e.response.status_code == 429:
                return (LLMProviderKey.State.ERROR, "Rate limited, please try again later")
            if e.response.status_code == 404:
                return (LLMProviderKey.State.INVALID, "Azure endpoint not found — check the URL")
            return (LLMProviderKey.State.ERROR, f"Azure OpenAI returned {e.response.status_code}")
        except httpx.HTTPError:
            return (LLMProviderKey.State.ERROR, "Could not connect to Azure OpenAI endpoint")
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

        if not azure_endpoint:
            return []

        try:
            return _list_azure_deployments(api_key, azure_endpoint)
        except httpx.HTTPStatusError as e:
            logger.exception(
                "Error listing Azure OpenAI deployments",
                extra={
                    "azure_endpoint": azure_endpoint,
                    "status_code": e.response.status_code,
                },
            )
            return []
        except Exception:
            logger.exception(
                "Error listing Azure OpenAI deployments",
                extra={"azure_endpoint": azure_endpoint},
            )
            return []

    @staticmethod
    def get_api_key() -> str:
        raise ValueError("Azure OpenAI is BYOKEY-only. No default API key is available.")

    def _get_default_api_key(self) -> str:
        raise ValueError("Azure OpenAI is BYOKEY-only. No default API key is available.")
