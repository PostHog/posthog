"""Tests for GeminiProvider shim that delegates to GeminiAdapter."""

import pytest
from unittest.mock import patch

from django.test import SimpleTestCase

from products.llm_analytics.backend.providers.gemini import GeminiConfig, GeminiProvider


class TestGeminiConfig(SimpleTestCase):
    def test_default_temperature(self):
        assert GeminiConfig.TEMPERATURE == 0

    def test_timeout_setting(self):
        assert GeminiConfig.TIMEOUT == 300

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
    def test_validate_model_accepts_supported_models(self):
        with patch.object(GeminiProvider, "__init__", lambda self, model_id, api_key=None: None):
            provider = GeminiProvider.__new__(GeminiProvider)
            provider.validate_model("gemini-2.0-flash")

    def test_validate_model_rejects_unsupported_models(self):
        with patch.object(GeminiProvider, "__init__", lambda self, model_id, api_key=None: None):
            provider = GeminiProvider.__new__(GeminiProvider)
            with pytest.raises(ValueError, match="not supported"):
                provider.validate_model("invalid-model")

    def test_prepare_config_kwargs_defaults(self):
        config = GeminiProvider.prepare_config_kwargs(system="Be helpful")
        assert config["temperature"] == GeminiConfig.TEMPERATURE
        assert config["system_instruction"] == "Be helpful"
        assert "max_output_tokens" not in config
        assert "tools" not in config

    def test_prepare_config_kwargs_with_overrides(self):
        config = GeminiProvider.prepare_config_kwargs(
            system="Be helpful",
            temperature=0.5,
            max_tokens=1000,
            tools=[{"name": "test_tool"}],
        )
        assert config["temperature"] == 0.5
        assert config["max_output_tokens"] == 1000
        assert config["tools"] == [{"name": "test_tool"}]

    def test_prepare_config_kwargs_empty_system(self):
        config = GeminiProvider.prepare_config_kwargs(system="")
        assert "system_instruction" not in config

    @patch("products.llm_analytics.backend.providers.gemini.GeminiAdapter")
    def test_get_api_key_delegates_to_adapter(self, mock_adapter_class):
        mock_adapter_class.get_api_key.return_value = "test-key"
        result = GeminiProvider.get_api_key()
        assert result == "test-key"
        mock_adapter_class.get_api_key.assert_called_once()
