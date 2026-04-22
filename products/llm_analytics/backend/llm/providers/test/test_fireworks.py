import pytest
from unittest.mock import MagicMock, patch

import openai

from products.llm_analytics.backend.llm.providers.fireworks import FIREWORKS_BASE_URL, FireworksAdapter


class TestFireworksValidateKey:
    @patch("products.llm_analytics.backend.llm.providers.fireworks.openai.OpenAI")
    def test_validate_key_valid_returns_ok(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_openai.return_value = mock_client

        state, message = FireworksAdapter.validate_key("fw-test-key")

        assert state == "ok"
        assert message is None

    @patch("products.llm_analytics.backend.llm.providers.fireworks.openai.OpenAI")
    def test_validate_key_auth_error_returns_invalid(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = openai.AuthenticationError(
            message="Invalid key",
            response=MagicMock(),
            body={},
        )
        mock_openai.return_value = mock_client

        state, message = FireworksAdapter.validate_key("fw-test-key")

        assert state == "invalid"
        assert message == "Invalid API key"

    @patch("products.llm_analytics.backend.llm.providers.fireworks.openai.OpenAI")
    def test_validate_key_connection_error_returns_error(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = openai.APIConnectionError(request=MagicMock())
        mock_openai.return_value = mock_client

        state, message = FireworksAdapter.validate_key("fw-test-key")

        assert state == "error"
        assert message == "Could not connect to Fireworks"

    @patch("products.llm_analytics.backend.llm.providers.fireworks.openai.OpenAI")
    def test_validate_key_rate_limit_returns_error(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = openai.RateLimitError(
            message="Rate limited",
            response=MagicMock(),
            body={},
        )
        mock_openai.return_value = mock_client

        state, message = FireworksAdapter.validate_key("fw-test-key")

        assert state == "error"
        assert message == "Rate limited, please try again later"


class TestFireworksListModels:
    def test_list_models_without_key_returns_empty(self):
        assert FireworksAdapter.list_models(None) == []

    @patch("products.llm_analytics.backend.llm.providers.fireworks.openai.OpenAI")
    def test_list_models_with_key_returns_newest_first(self, mock_openai):
        model_older = MagicMock()
        model_older.id = "accounts/fireworks/models/deepseek-r1"
        model_older.created = 1700000000

        model_newer = MagicMock()
        model_newer.id = "accounts/fireworks/models/llama-v3p3-70b-instruct"
        model_newer.created = 1710000000

        mock_client = MagicMock()
        mock_client.models.list.return_value = [model_older, model_newer]
        mock_openai.return_value = mock_client

        models = FireworksAdapter.list_models("fw-test-key")

        assert models == [
            "accounts/fireworks/models/llama-v3p3-70b-instruct",
            "accounts/fireworks/models/deepseek-r1",
        ]

    @patch("products.llm_analytics.backend.llm.providers.fireworks.openai.OpenAI", side_effect=Exception("API error"))
    def test_list_models_error_returns_empty(self, _mock_openai):
        assert FireworksAdapter.list_models("fw-test-key") == []

    @patch("products.llm_analytics.backend.llm.providers.fireworks.openai.OpenAI")
    def test_list_models_uses_fireworks_base_url(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_openai.return_value = mock_client

        FireworksAdapter.list_models("fw-test-key")

        mock_openai.assert_called_once()
        assert mock_openai.call_args.kwargs["base_url"] == FIREWORKS_BASE_URL


class TestFireworksRecommendedModels:
    def test_recommended_models_returns_empty(self):
        assert FireworksAdapter.recommended_models() == set()


class TestFireworksDefaultKey:
    def test_get_api_key_raises(self):
        with pytest.raises(ValueError, match="BYOKEY-only"):
            FireworksAdapter.get_api_key()

    def test_get_default_api_key_raises(self):
        adapter = FireworksAdapter()

        with pytest.raises(ValueError, match="BYOKEY-only"):
            adapter._get_default_api_key()
