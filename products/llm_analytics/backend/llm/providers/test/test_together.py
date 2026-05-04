import pytest
from unittest.mock import MagicMock, patch

import httpx
from parameterized import parameterized

from products.llm_analytics.backend.llm.providers.openai import OpenAIConfig
from products.llm_analytics.backend.llm.providers.together import TOGETHER_MODELS_URL, TogetherAdapter


class TestTogetherValidateKey:
    @parameterized.expand(
        [
            ("valid", 200, "ok", None),
            ("auth_error", 401, "invalid", "Invalid API key"),
            ("rate_limit", 429, "error", "Rate limited, please try again later"),
            ("server_error", 500, "error", "Unexpected response status: 500"),
        ]
    )
    def test_validate_key_status_codes(self, _name, status_code, expected_state, expected_message):
        mock_response = MagicMock()
        mock_response.status_code = status_code

        with patch(
            "products.llm_analytics.backend.llm.providers.together._get_models_response", return_value=mock_response
        ):
            state, message = TogetherAdapter.validate_key("together-test-key")

        assert state == expected_state
        assert message == expected_message

    @parameterized.expand(
        [
            ("timeout", httpx.TimeoutException("timeout"), "Request timed out, please try again"),
            ("connection_error", httpx.ConnectError("connection refused"), "Could not connect to Together AI"),
        ]
    )
    def test_validate_key_http_errors(self, _name, side_effect, expected_message):
        with patch(
            "products.llm_analytics.backend.llm.providers.together._get_models_response", side_effect=side_effect
        ):
            state, message = TogetherAdapter.validate_key("together-test-key")

        assert state == "error"
        assert message == expected_message


class TestTogetherListModels:
    def test_list_models_without_key_returns_empty(self):
        assert TogetherAdapter.list_models(None) == []

    def test_list_models_with_key_returns_newest_first(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "created": 1700000000},
            {"id": "Qwen/Qwen3.5-397B-A17B", "created": 1710000000},
        ]

        with patch(
            "products.llm_analytics.backend.llm.providers.together._get_models_response", return_value=mock_response
        ):
            models = TogetherAdapter.list_models("together-test-key")

        assert models == [
            "Qwen/Qwen3.5-397B-A17B",
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        ]

    @patch(
        "products.llm_analytics.backend.llm.providers.together._get_models_response",
        side_effect=httpx.HTTPError("API error"),
    )
    def test_list_models_error_returns_empty(self, _mock_get_models_response):
        assert TogetherAdapter.list_models("together-test-key") == []

    @patch("products.llm_analytics.backend.llm.providers.together.httpx.get")
    def test_list_models_uses_together_models_endpoint(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_get.return_value = mock_response

        TogetherAdapter.list_models("together-test-key")

        mock_get.assert_called_once_with(
            TOGETHER_MODELS_URL,
            headers={"Authorization": "Bearer together-test-key"},
            timeout=OpenAIConfig.TIMEOUT,
        )


class TestTogetherRecommendedModels:
    def test_recommended_models_returns_empty(self):
        assert TogetherAdapter.recommended_models() == set()


class TestTogetherDefaultKey:
    def test_get_api_key_raises(self):
        with pytest.raises(ValueError, match="BYOKEY-only"):
            TogetherAdapter.get_api_key()

    def test_get_default_api_key_raises(self):
        adapter = TogetherAdapter()

        with pytest.raises(ValueError, match="BYOKEY-only"):
            adapter._get_default_api_key()
