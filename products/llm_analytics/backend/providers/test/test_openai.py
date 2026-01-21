from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from products.llm_analytics.backend.providers.openai import OpenAIConfig, OpenAIProvider


class TestOpenAIProvider(SimpleTestCase):
    @override_settings(OPENAI_API_KEY="test-api-key", OPENAI_BASE_URL="https://api.openai.com/v1")
    @patch("products.llm_analytics.backend.providers.openai.OpenAI")
    @patch("posthoganalytics.default_client")
    def test_provider_initialization(self, mock_posthog_client, mock_openai_client):
        mock_posthog_client.return_value = MagicMock()

        provider = OpenAIProvider("gpt-4o")

        assert provider.model_id == "gpt-4o"
        mock_openai_client.assert_called_once()
        call_kwargs = mock_openai_client.call_args[1]
        assert call_kwargs["api_key"] == "test-api-key"
        assert call_kwargs["posthog_client"] == mock_posthog_client
        assert call_kwargs["timeout"] == OpenAIConfig.TIMEOUT
