"""Tests for AnthropicProvider shim that delegates to AnthropicAdapter."""

from unittest.mock import patch

from django.test import SimpleTestCase

from products.llm_analytics.backend.providers.anthropic import AnthropicConfig, AnthropicProvider


class TestAnthropicConfig(SimpleTestCase):
    def test_default_temperature(self):
        assert AnthropicConfig.TEMPERATURE == 0

    def test_timeout_setting(self):
        assert AnthropicConfig.TIMEOUT == 300.0

    def test_max_tokens_setting(self):
        assert AnthropicConfig.MAX_TOKENS == 8192

    def test_supported_models_include_expected(self):
        expected_models = [
            "claude-haiku-4-5",
            "claude-sonnet-4-5",
            "claude-opus-4-5",
        ]
        for model in expected_models:
            assert model in AnthropicConfig.SUPPORTED_MODELS


class TestAnthropicProviderShim(SimpleTestCase):
    @patch("products.llm_analytics.backend.providers.anthropic.AnthropicAdapter")
    def test_get_api_key_delegates_to_adapter(self, mock_adapter_class):
        mock_adapter_class.get_api_key.return_value = "test-key"
        result = AnthropicProvider.get_api_key()
        assert result == "test-key"
        mock_adapter_class.get_api_key.assert_called_once()

    @patch("products.llm_analytics.backend.providers.anthropic.AnthropicAdapter")
    def test_initialization_sets_model_id(self, mock_adapter_class):
        provider = AnthropicProvider("claude-sonnet-4-5")
        assert provider.model_id == "claude-sonnet-4-5"

    @patch("products.llm_analytics.backend.providers.anthropic.AnthropicAdapter")
    def test_initialization_with_custom_api_key(self, mock_adapter_class):
        provider = AnthropicProvider("claude-sonnet-4-5", api_key="custom-key")
        assert provider._api_key == "custom-key"
