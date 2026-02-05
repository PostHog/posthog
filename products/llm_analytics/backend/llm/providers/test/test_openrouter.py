import pytest
from unittest.mock import MagicMock, patch

import httpx
from parameterized import parameterized

from products.llm_analytics.backend.llm.providers.openrouter import OpenRouterAdapter


class TestOpenRouterValidateKey:
    @parameterized.expand(
        [
            ("valid_key_returns_ok", 200, "ok", None),
            ("invalid_key_returns_invalid", 401, "invalid", "Invalid API key"),
            ("server_error_returns_error", 500, "error", "Unexpected response status: 500"),
        ]
    )
    def test_validate_key_status_codes(self, _name, status_code, expected_state, expected_message):
        mock_response = MagicMock()
        mock_response.status_code = status_code

        with patch("products.llm_analytics.backend.llm.providers.openrouter.httpx.get", return_value=mock_response):
            state, message = OpenRouterAdapter.validate_key("sk-or-test-key")

        assert state == expected_state
        assert message == expected_message

    def test_validate_key_timeout_returns_error(self):
        with patch(
            "products.llm_analytics.backend.llm.providers.openrouter.httpx.get",
            side_effect=httpx.TimeoutException("timeout"),
        ):
            state, message = OpenRouterAdapter.validate_key("sk-or-test-key")

        assert state == "error"
        assert message == "Request timed out, please try again"

    def test_validate_key_connection_error_returns_error(self):
        with patch(
            "products.llm_analytics.backend.llm.providers.openrouter.httpx.get",
            side_effect=httpx.ConnectError("connection refused"),
        ):
            state, message = OpenRouterAdapter.validate_key("sk-or-test-key")

        assert state == "error"
        assert message == "Could not connect to OpenRouter"


class TestOpenRouterListModels:
    def test_list_models_without_key_returns_empty(self):
        assert OpenRouterAdapter.list_models(None) == []

    def test_list_models_with_key_returns_sorted_ids(self):
        mock_model_b = MagicMock()
        mock_model_b.id = "openai/gpt-4o"
        mock_model_a = MagicMock()
        mock_model_a.id = "anthropic/claude-3.5-sonnet"

        mock_client = MagicMock()
        mock_client.models.list.return_value = [mock_model_b, mock_model_a]

        with patch("products.llm_analytics.backend.llm.providers.openrouter.openai.OpenAI", return_value=mock_client):
            models = OpenRouterAdapter.list_models("sk-or-test-key")

        assert models == ["anthropic/claude-3.5-sonnet", "openai/gpt-4o"]

    def test_list_models_error_returns_empty(self):
        with patch(
            "products.llm_analytics.backend.llm.providers.openrouter.openai.OpenAI",
            side_effect=Exception("API error"),
        ):
            models = OpenRouterAdapter.list_models("sk-or-test-key")

        assert models == []


class TestOpenRouterDefaultKey:
    def test_get_api_key_raises(self):
        with pytest.raises(ValueError, match="BYOKEY-only"):
            OpenRouterAdapter.get_api_key()

    def test_get_default_api_key_raises(self):
        adapter = OpenRouterAdapter()

        with pytest.raises(ValueError, match="BYOKEY-only"):
            adapter._get_default_api_key()
