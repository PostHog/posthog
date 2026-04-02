from unittest.mock import MagicMock, patch

from products.llm_analytics.backend.llm.providers.anthropic import AnthropicAdapter, AnthropicConfig


class TestAnthropicListModels:
    def test_list_models_without_key_returns_supported(self):
        assert AnthropicAdapter.list_models(None) == AnthropicConfig.SUPPORTED_MODELS

    @patch("products.llm_analytics.backend.llm.providers.anthropic.anthropic.Anthropic")
    def test_list_models_with_key_returns_supported_plus_api_models_newest_first(self, mock_anthropic):
        api_model_supported = MagicMock()
        api_model_supported.id = "claude-opus-4-5"
        api_model_supported.created_at = "2025-06-01T00:00:00Z"

        api_model_new = MagicMock()
        api_model_new.id = "claude-5-opus"
        api_model_new.created_at = "2026-03-01T00:00:00Z"

        api_model_old = MagicMock()
        api_model_old.id = "claude-3-haiku-20240307"
        api_model_old.created_at = "2024-03-07T00:00:00Z"

        mock_page = MagicMock()
        mock_page.data = [api_model_supported, api_model_new, api_model_old]

        mock_client = MagicMock()
        mock_client.models.list.return_value = mock_page
        mock_anthropic.return_value = mock_client

        models = AnthropicAdapter.list_models("sk-ant-test-key")

        # Supported models first, then API models sorted by created_at newest first
        assert models == [*AnthropicConfig.SUPPORTED_MODELS, "claude-5-opus", "claude-3-haiku-20240307"]

    @patch("products.llm_analytics.backend.llm.providers.anthropic.anthropic.Anthropic")
    def test_list_models_filters_non_claude_models(self, mock_anthropic):
        claude_model = MagicMock()
        claude_model.id = "claude-instant-1.2"

        non_claude_model = MagicMock()
        non_claude_model.id = "some-other-model"

        mock_page = MagicMock()
        mock_page.data = [claude_model, non_claude_model]

        mock_client = MagicMock()
        mock_client.models.list.return_value = mock_page
        mock_anthropic.return_value = mock_client

        models = AnthropicAdapter.list_models("sk-ant-test-key")

        assert "claude-instant-1.2" in models
        assert "some-other-model" not in models

    @patch(
        "products.llm_analytics.backend.llm.providers.anthropic.anthropic.Anthropic",
        side_effect=Exception("API error"),
    )
    def test_list_models_error_returns_supported(self, _mock_anthropic):
        assert AnthropicAdapter.list_models("sk-ant-test-key") == AnthropicConfig.SUPPORTED_MODELS


class TestAnthropicRecommendedModels:
    def test_recommended_models_equals_supported_models(self):
        assert AnthropicAdapter.recommended_models() == set(AnthropicConfig.SUPPORTED_MODELS)
