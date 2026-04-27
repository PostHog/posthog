import pytest
from unittest.mock import MagicMock, patch

import openai

from products.llm_analytics.backend.llm.providers.minimax import MINIMAX_BASE_URL, MINIMAX_MODELS, MiniMaxAdapter


class TestMiniMaxValidateKey:
    @patch("products.llm_analytics.backend.llm.providers.minimax.openai.OpenAI")
    def test_validate_key_valid_returns_ok(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_openai.return_value = mock_client

        state, message = MiniMaxAdapter.validate_key("test-minimax-key")

        assert state == "ok"
        assert message is None

    @patch("products.llm_analytics.backend.llm.providers.minimax.openai.OpenAI")
    def test_validate_key_auth_error_returns_invalid(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = openai.AuthenticationError(
            message="Invalid key",
            response=MagicMock(),
            body={},
        )
        mock_openai.return_value = mock_client

        state, message = MiniMaxAdapter.validate_key("test-minimax-key")

        assert state == "invalid"
        assert message == "Invalid API key"

    @patch("products.llm_analytics.backend.llm.providers.minimax.openai.OpenAI")
    def test_validate_key_connection_error_returns_error(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = openai.APIConnectionError(request=MagicMock())
        mock_openai.return_value = mock_client

        state, message = MiniMaxAdapter.validate_key("test-minimax-key")

        assert state == "error"
        assert message == "Could not connect to MiniMax"

    @patch("products.llm_analytics.backend.llm.providers.minimax.openai.OpenAI")
    def test_validate_key_rate_limit_returns_error(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = openai.RateLimitError(
            message="Rate limited",
            response=MagicMock(),
            body={},
        )
        mock_openai.return_value = mock_client

        state, message = MiniMaxAdapter.validate_key("test-minimax-key")

        assert state == "error"
        assert message == "Rate limited, please try again later"


class TestMiniMaxListModels:
    def test_list_models_without_key_returns_curated(self):
        models = MiniMaxAdapter.list_models(None)
        assert models == MINIMAX_MODELS
        assert "MiniMax-M2.7" in models
        assert "MiniMax-M2.7-highspeed" in models

    @patch("products.llm_analytics.backend.llm.providers.minimax.openai.OpenAI")
    def test_list_models_with_key_prepends_curated(self, mock_openai):
        model_extra = MagicMock()
        model_extra.id = "MiniMax-Text-01"
        model_extra.created = 1700000000

        mock_client = MagicMock()
        mock_client.models.list.return_value = [model_extra]
        mock_openai.return_value = mock_client

        models = MiniMaxAdapter.list_models("test-minimax-key")

        assert models[:2] == MINIMAX_MODELS
        assert "MiniMax-Text-01" in models

    @patch("products.llm_analytics.backend.llm.providers.minimax.openai.OpenAI", side_effect=Exception("API error"))
    def test_list_models_error_returns_curated(self, _mock_openai):
        assert MiniMaxAdapter.list_models("test-minimax-key") == list(MINIMAX_MODELS)

    @patch("products.llm_analytics.backend.llm.providers.minimax.openai.OpenAI")
    def test_list_models_uses_minimax_base_url(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_openai.return_value = mock_client

        MiniMaxAdapter.list_models("test-minimax-key")

        mock_openai.assert_called_once()
        assert mock_openai.call_args.kwargs["base_url"] == MINIMAX_BASE_URL


class TestMiniMaxRecommendedModels:
    def test_recommended_models_returns_curated_set(self):
        recommended = MiniMaxAdapter.recommended_models()
        assert "MiniMax-M2.7" in recommended
        assert "MiniMax-M2.7-highspeed" in recommended


class TestMiniMaxDefaultKey:
    def test_get_api_key_raises(self):
        with pytest.raises(ValueError, match="BYOKEY-only"):
            MiniMaxAdapter.get_api_key()

    def test_get_default_api_key_raises(self):
        adapter = MiniMaxAdapter()

        with pytest.raises(ValueError, match="BYOKEY-only"):
            adapter._get_default_api_key()


class TestMiniMaxBaseUrl:
    def test_base_url_is_minimax_io(self):
        assert MINIMAX_BASE_URL == "https://api.minimax.io/v1"

    @patch("products.llm_analytics.backend.llm.providers.openai.OpenAIAdapter.complete")
    def test_complete_passes_minimax_base_url(self, mock_complete):
        from products.llm_analytics.backend.llm.types import AnalyticsContext, CompletionRequest

        adapter = MiniMaxAdapter()
        request = MagicMock(spec=CompletionRequest)
        request.provider = "minimax"
        analytics = MagicMock(spec=AnalyticsContext)

        adapter.complete(request, "test-key", analytics)

        mock_complete.assert_called_once_with(request, "test-key", analytics, base_url=MINIMAX_BASE_URL)

    @patch("products.llm_analytics.backend.llm.providers.openai.OpenAIAdapter.stream")
    def test_stream_passes_minimax_base_url(self, mock_stream):
        from products.llm_analytics.backend.llm.types import AnalyticsContext, CompletionRequest

        mock_stream.return_value = iter([])

        adapter = MiniMaxAdapter()
        request = MagicMock(spec=CompletionRequest)
        request.provider = "minimax"
        analytics = MagicMock(spec=AnalyticsContext)

        list(adapter.stream(request, "test-key", analytics))

        mock_stream.assert_called_once_with(request, "test-key", analytics, base_url=MINIMAX_BASE_URL)
