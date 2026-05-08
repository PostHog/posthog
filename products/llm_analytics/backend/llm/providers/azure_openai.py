"""Azure OpenAI provider for unified LLM client.

Azure OpenAI uses deployment-based model naming and requires an azure_endpoint
and api_version in addition to an API key. This provider is BYOK-only.
"""

import logging
from typing import Any
from urllib.parse import urlparse

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
# If this call starts 400-ing, Azure has retired the preview; bump to the latest authoring
# version from https://learn.microsoft.com/en-us/azure/ai-services/openai/api-version-deprecation.
DEPLOYMENTS_LIST_API_VERSION = "2023-03-15-preview"

# Listing is a cheap call; don't inherit the long completion timeout.
AZURE_LIST_TIMEOUT = 10.0

# Allowed DNS suffixes for Azure OpenAI endpoints. Restricts outbound requests (with the user's
# API key in the header) to legitimate Azure hosts — prevents the user-controlled endpoint from
# being pointed at internal metadata services, arbitrary corp infra, or typo'd hosts.
_ALLOWED_ENDPOINT_SUFFIXES: tuple[str, ...] = (
    ".openai.azure.com",
    ".cognitiveservices.azure.com",
    ".services.ai.azure.com",
)

# Shared error message used by both the adapter (for `Client.validate_key` callers) and the
# serializer layer (so the error attributes to the azure_endpoint field in the UI). Keep as a
# single source of truth — the two layers must agree.
DISALLOWED_ENDPOINT_MESSAGE = "Azure endpoint must be an https:// URL on an Azure domain (e.g. *.openai.azure.com)"

# Maps adapter error-message prefixes to the form field they should highlight in the UI.
# Keep aligned with the `return` statements in `AzureOpenAIAdapter.validate_key` below —
# editing a message string there without updating this table silently breaks field routing.
# Messages not listed (rate limits, 5xx, generic failures) have no field attribution and are
# surfaced as toast/banner by the frontend.
_ERROR_FIELD_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("Azure endpoint is required", "azure_endpoint"),
    ("Azure endpoint must be", "azure_endpoint"),
    ("Azure endpoint not found", "azure_endpoint"),
    ("Could not connect to Azure", "azure_endpoint"),
    ("Invalid API key", "api_key"),
)


def error_field_for_validation_message(error_message: str | None) -> str | None:
    """Map an Azure `validate_key` error message to the UI form field that should be highlighted."""
    if not error_message:
        return None
    return next(
        (field for prefix, field in _ERROR_FIELD_BY_PREFIX if error_message.startswith(prefix)),
        None,
    )


def is_allowed_azure_endpoint(azure_endpoint: str) -> bool:
    """Return True if the endpoint is https:// and its host ends with an allowed Azure DNS suffix."""
    if not azure_endpoint:
        return False
    try:
        parsed = urlparse(azure_endpoint)
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(host.endswith(suffix) for suffix in _ALLOWED_ENDPOINT_SUFFIXES)


def _list_azure_deployments(api_key: str, azure_endpoint: str) -> list[str]:
    """List Azure OpenAI deployments.

    The openai SDK's `client.models.list()` returns the Azure model *catalog*,
    not the user-created deployments. Chat completions require a deployment
    name, so we hit the data-plane `/openai/deployments` endpoint directly.
    """
    # Defense-in-depth: callers are expected to have already passed the endpoint
    # through `is_allowed_azure_endpoint`, but we re-assert here so this function
    # cannot be misused by a future caller and leak the API key to a non-Azure host.
    if not is_allowed_azure_endpoint(azure_endpoint):
        raise ValueError("azure_endpoint failed allowlist check")

    endpoint = azure_endpoint.rstrip("/")
    url = f"{endpoint}/openai/deployments"

    # `follow_redirects=False` is an explicit SSRF regression guard — even if an Azure
    # host ever returned a 3xx pointing elsewhere, httpx must not re-send the api-key
    # header to the redirect target.
    response = httpx.get(
        url,
        params={"api-version": DEPLOYMENTS_LIST_API_VERSION},
        headers={"api-key": api_key},
        timeout=AZURE_LIST_TIMEOUT,
        follow_redirects=False,
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

        if not is_allowed_azure_endpoint(azure_endpoint):
            return (LLMProviderKey.State.INVALID, DISALLOWED_ENDPOINT_MESSAGE)

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
        except Exception:
            logger.exception("Azure OpenAI key validation error")
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

        if not azure_endpoint or not is_allowed_azure_endpoint(azure_endpoint):
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
