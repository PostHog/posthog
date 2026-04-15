import pytest
from unittest.mock import MagicMock, patch

import openai

from products.llm_analytics.backend.llm.providers.azure_openai import DEFAULT_API_VERSION, AzureOpenAIAdapter

MOCK_ENDPOINT = "https://my-resource.openai.azure.com/"


class TestAzureOpenAIValidateKey:
    @patch("products.llm_analytics.backend.llm.providers.azure_openai.openai.AzureOpenAI")
    def test_validate_key_valid_returns_ok(self, mock_azure):
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_azure.return_value = mock_client

        state, message = AzureOpenAIAdapter.validate_key("hex-api-key-123", azure_endpoint=MOCK_ENDPOINT)

        assert state == "ok"
        assert message is None
        mock_azure.assert_called_once()
        assert mock_azure.call_args.kwargs["azure_endpoint"] == MOCK_ENDPOINT
        assert mock_azure.call_args.kwargs["api_version"] == DEFAULT_API_VERSION

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.openai.AzureOpenAI")
    def test_validate_key_auth_error_returns_invalid(self, mock_azure):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = openai.AuthenticationError(
            message="Invalid key",
            response=MagicMock(),
            body={},
        )
        mock_azure.return_value = mock_client

        state, message = AzureOpenAIAdapter.validate_key("bad-key", azure_endpoint=MOCK_ENDPOINT)

        assert state == "invalid"
        assert message == "Invalid API key"

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.openai.AzureOpenAI")
    def test_validate_key_connection_error_returns_error(self, mock_azure):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = openai.APIConnectionError(request=MagicMock())
        mock_azure.return_value = mock_client

        state, message = AzureOpenAIAdapter.validate_key("key", azure_endpoint=MOCK_ENDPOINT)

        assert state == "error"
        assert message == "Could not connect to Azure OpenAI endpoint"

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.openai.AzureOpenAI")
    def test_validate_key_rate_limit_returns_error(self, mock_azure):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = openai.RateLimitError(
            message="Rate limited",
            response=MagicMock(),
            body={},
        )
        mock_azure.return_value = mock_client

        state, message = AzureOpenAIAdapter.validate_key("key", azure_endpoint=MOCK_ENDPOINT)

        assert state == "error"
        assert message == "Rate limited, please try again later"

    def test_validate_key_missing_endpoint_returns_invalid(self):
        state, message = AzureOpenAIAdapter.validate_key("key")

        assert state == "invalid"
        assert message == "Azure endpoint is required"

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.openai.AzureOpenAI")
    def test_validate_key_custom_api_version(self, mock_azure):
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_azure.return_value = mock_client

        AzureOpenAIAdapter.validate_key("key", azure_endpoint=MOCK_ENDPOINT, api_version="2025-01-01")

        assert mock_azure.call_args.kwargs["api_version"] == "2025-01-01"


class TestAzureOpenAIListModels:
    def test_list_models_without_key_returns_empty(self):
        assert AzureOpenAIAdapter.list_models(None) == []

    def test_list_models_without_endpoint_returns_empty(self):
        assert AzureOpenAIAdapter.list_models("key") == []

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.openai.AzureOpenAI")
    def test_list_models_with_key_returns_deployment_names(self, mock_azure):
        deployment_older = MagicMock()
        deployment_older.id = "my-gpt4-deployment"
        deployment_older.created = 1700000000

        deployment_newer = MagicMock()
        deployment_newer.id = "my-gpt4o-deployment"
        deployment_newer.created = 1710000000

        mock_client = MagicMock()
        mock_client.models.list.return_value = [deployment_older, deployment_newer]
        mock_azure.return_value = mock_client

        models = AzureOpenAIAdapter.list_models("key", azure_endpoint=MOCK_ENDPOINT)

        assert models == ["my-gpt4o-deployment", "my-gpt4-deployment"]

    @patch(
        "products.llm_analytics.backend.llm.providers.azure_openai.openai.AzureOpenAI",
        side_effect=Exception("API error"),
    )
    def test_list_models_error_returns_empty(self, _mock_azure):
        assert AzureOpenAIAdapter.list_models("key", azure_endpoint=MOCK_ENDPOINT) == []

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.openai.AzureOpenAI")
    def test_list_models_uses_azure_endpoint(self, mock_azure):
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_azure.return_value = mock_client

        AzureOpenAIAdapter.list_models("key", azure_endpoint=MOCK_ENDPOINT)

        mock_azure.assert_called_once()
        assert mock_azure.call_args.kwargs["azure_endpoint"] == MOCK_ENDPOINT


class TestAzureOpenAIRecommendedModels:
    def test_recommended_models_returns_empty(self):
        assert AzureOpenAIAdapter.recommended_models() == set()


class TestAzureOpenAIDefaultKey:
    def test_get_api_key_raises(self):
        with pytest.raises(ValueError, match="BYOKEY-only"):
            AzureOpenAIAdapter.get_api_key()

    def test_get_default_api_key_raises(self):
        adapter = AzureOpenAIAdapter()

        with pytest.raises(ValueError, match="BYOKEY-only"):
            adapter._get_default_api_key()


class TestAzureOpenAICreateClient:
    @patch("products.llm_analytics.backend.llm.providers.azure_openai.openai.AzureOpenAI")
    def test_create_client_uses_azure_config(self, mock_azure):
        from products.llm_analytics.backend.llm.types import AnalyticsContext

        adapter = AzureOpenAIAdapter(azure_endpoint=MOCK_ENDPOINT, api_version="2025-01-01")
        analytics = AnalyticsContext(distinct_id="test", capture=False)

        adapter._create_client("test-key", None, analytics)

        mock_azure.assert_called_once()
        assert mock_azure.call_args.kwargs["api_key"] == "test-key"
        assert mock_azure.call_args.kwargs["azure_endpoint"] == MOCK_ENDPOINT
        assert mock_azure.call_args.kwargs["api_version"] == "2025-01-01"

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.openai.AzureOpenAI")
    def test_create_client_ignores_base_url(self, mock_azure):
        from products.llm_analytics.backend.llm.types import AnalyticsContext

        adapter = AzureOpenAIAdapter(azure_endpoint=MOCK_ENDPOINT)
        analytics = AnalyticsContext(distinct_id="test", capture=False)

        adapter._create_client("test-key", "https://ignored.example.com", analytics)

        mock_azure.assert_called_once()
        assert mock_azure.call_args.kwargs["azure_endpoint"] == MOCK_ENDPOINT
        assert "base_url" not in mock_azure.call_args.kwargs
