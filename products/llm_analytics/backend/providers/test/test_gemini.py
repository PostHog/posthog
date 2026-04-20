"""Tests for GeminiProvider shim that delegates to GeminiAdapter."""

import pytest
from unittest.mock import patch

from django.test import SimpleTestCase

from products.llm_analytics.backend.providers.gemini import GeminiConfig, GeminiProvider


class TestGeminiConfig(SimpleTestCase):
    def test_default_temperature(self):
        assert GeminiConfig.TEMPERATURE == 0

    def test_timeout_setting(self):
        assert GeminiConfig.TIMEOUT == 300_000

    def test_supported_models_include_expected(self):
        expected_models = [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ]
        for model in expected_models:
            assert model in GeminiConfig.SUPPORTED_MODELS


class TestGeminiProviderShim(SimpleTestCase):
    @patch("products.llm_analytics.backend.providers.gemini.GeminiAdapter")
    def test_get_api_key_delegates_to_adapter(self, mock_adapter_class):
        mock_adapter_class.get_api_key.return_value = "test-key"
        result = GeminiProvider.get_api_key()
        assert result == "test-key"
        mock_adapter_class.get_api_key.assert_called_once()

    def test_validate_model_accepts_supported_model(self):
        provider = GeminiProvider(model_id="gemini-2.5-flash")
        provider.validate_model("gemini-2.5-flash")

    def test_validate_model_rejects_unsupported_model(self):
        provider = GeminiProvider(model_id="gemini-2.5-flash")
        with pytest.raises(ValueError) as exc_info:
            provider.validate_model("unsupported-model")
        assert "unsupported-model" in str(exc_info.value)

    @patch("products.llm_analytics.backend.providers.gemini.GeminiAdapter._prepare_config_kwargs")
    def test_prepare_config_kwargs_delegates_to_adapter(self, mock_prepare):
        mock_prepare.return_value = {"temperature": 0}
        result = GeminiProvider.prepare_config_kwargs(system="test")
        assert result == {"temperature": 0}
        mock_prepare.assert_called_once_with("test", None, None, None)
