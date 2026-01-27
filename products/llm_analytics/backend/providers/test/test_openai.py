"""Tests for OpenAIProvider shim that delegates to OpenAIAdapter."""

from unittest.mock import patch

from django.test import SimpleTestCase

from products.llm_analytics.backend.providers.openai import OpenAIConfig, OpenAIProvider


class TestOpenAIConfig(SimpleTestCase):
    def test_default_temperature(self):
        assert OpenAIConfig.TEMPERATURE == 0

    def test_supported_models_include_expected(self):
        expected_models = [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-5",
            "gpt-5-mini",
            "o3",
            "o3-mini",
        ]
        for model in expected_models:
            assert model in OpenAIConfig.SUPPORTED_MODELS


class TestOpenAIProviderShim(SimpleTestCase):
    @patch("products.llm_analytics.backend.providers.openai.OpenAIAdapter")
    def test_get_api_key_delegates_to_adapter(self, mock_adapter_class):
        mock_adapter_class.get_api_key.return_value = "test-key"
        result = OpenAIProvider.get_api_key()
        assert result == "test-key"
        mock_adapter_class.get_api_key.assert_called_once()

    @patch("products.llm_analytics.backend.providers.openai.OpenAIAdapter")
    def test_initialization_sets_model_id(self, mock_adapter_class):
        provider = OpenAIProvider("gpt-4o")
        assert provider.model_id == "gpt-4o"

    @patch("products.llm_analytics.backend.providers.openai.OpenAIAdapter")
    def test_initialization_with_custom_api_key(self, mock_adapter_class):
        provider = OpenAIProvider("gpt-4o", api_key="custom-key")
        assert provider._api_key == "custom-key"
