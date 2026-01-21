from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from products.llm_analytics.backend.providers.anthropic import AnthropicConfig, AnthropicProvider


class TestAnthropicProvider(SimpleTestCase):
    @override_settings(ANTHROPIC_API_KEY="test-api-key")
    @patch("products.llm_analytics.backend.providers.anthropic.Anthropic")
    @patch("posthoganalytics.default_client")
    def test_provider_initialization(self, mock_posthog_client, mock_anthropic_client):
        mock_posthog_client.return_value = MagicMock()

        provider = AnthropicProvider("claude-sonnet-4-5")

        assert provider.model_id == "claude-sonnet-4-5"
        mock_anthropic_client.assert_called_once()
        call_kwargs = mock_anthropic_client.call_args[1]
        assert call_kwargs["api_key"] == "test-api-key"
        assert call_kwargs["posthog_client"] == mock_posthog_client
        assert call_kwargs["timeout"] == AnthropicConfig.TIMEOUT
