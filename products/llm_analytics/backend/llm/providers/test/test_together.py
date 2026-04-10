import pytest
from unittest.mock import MagicMock, patch

import openai

from products.llm_analytics.backend.llm.providers.together import TOGETHER_BASE_URL, TogetherAdapter


class TestTogetherValidateKey:
    @patch("products.llm_analytics.backend.llm.providers.together.openai.OpenAI")
    def test_validate_key_valid_returns_ok(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_openai.return_value = mock_client

        state, message = TogetherAdapter.validate_key("together-test-key")

        assert state == "ok"
        assert message is None

    @patch("products.llm_analytics.backend.llm.providers.together.openai.OpenAI")
    def test_validate_key_auth_error_returns_invalid(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = openai.AuthenticationError(
            message="Invalid key",
            response=MagicMock(),
            body={},
        )
        mock_openai.return_value = mock_client

        state, message = TogetherAdapter.validate_key("together-test-key")

        assert state == "invalid"
        assert message == "Invalid API key"

    @patch("products.llm_analytics.backend.llm.providers.together.openai.OpenAI")
    def test_validate_key_connection_error_returns_error(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = openai.APIConnectionError(request=MagicMock())
        mock_openai.return_value = mock_client

        state, message = TogetherAdapter.validate_key("together-test-key")

        assert state == "error"
        assert message == "Could not connect to Together AI"

    @patch("products.llm_analytics.backend.llm.providers.together.openai.OpenAI")
    def test_validate_key_rate_limit_returns_error(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = openai.RateLimitError(
            message="Rate limited",
            response=MagicMock(),
            body={},
        )
        mock_openai.return_value = mock_client

        state, message = TogetherAdapter.validate_key("together-test-key")

        assert state == "error"
        assert message == "Rate limited, please try again later"


class TestTogetherListModels:
    def test_list_models_without_key_returns_empty(self):
        assert TogetherAdapter.list_models(None) == []

    @patch("products.llm_analytics.backend.llm.providers.together.openai.OpenAI")
    def test_list_models_with_key_returns_newest_first(self, mock_openai):
        model_older = MagicMock()
        model_older.id = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
        model_older.created = 1700000000

        model_newer = MagicMock()
        model_newer.id = "Qwen/Qwen3.5-397B-A17B"
        model_newer.created = 1710000000

        mock_client = MagicMock()
        mock_client.models.list.return_value = [model_older, model_newer]
        mock_openai.return_value = mock_client

        models = TogetherAdapter.list_models("together-test-key")

        assert models == [
            "Qwen/Qwen3.5-397B-A17B",
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        ]

    @patch(
        "products.llm_analytics.backend.llm.providers.together.openai.OpenAI",
        side_effect=Exception("API error"),
    )
    def test_list_models_error_returns_recommended(self, _mock_openai):
        assert TogetherAdapter.list_models("together-test-key") == []

    @patch("products.llm_analytics.backend.llm.providers.together.openai.OpenAI")
    def test_list_models_uses_together_base_url(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_openai.return_value = mock_client

        TogetherAdapter.list_models("together-test-key")

        mock_openai.assert_called_once()
        assert mock_openai.call_args.kwargs["base_url"] == TOGETHER_BASE_URL


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
