import pytest
from unittest.mock import Mock, patch
from anthropic.types import MessageParam
from google.genai.errors import APIError
from products.editor.backend.providers.gemini import GeminiProvider
from django.test import TestCase


@patch("django.conf.settings.GEMINI_API_KEY", "test-key")
class TestGeminiProvider(TestCase):
    def setUp(self):
        self.model_id = "gemini-1.5-flash"

    def test_validate_model(self):
        GeminiProvider(self.model_id)
        with pytest.raises(ValueError, match="Model invalid-model is not supported"):
            GeminiProvider("invalid-model")

    @patch("google.genai.Client")
    def test_stream_response_success(self, mock_client_class):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_model = Mock()
        mock_client.models = mock_model

        # Create concrete response objects instead of MagicMocks
        class MockResponse1:
            text = "test response"
            usage_metadata = None

        class MockResponse2:
            text = None

            class UsageMetadata:
                prompt_token_count = 10
                candidates_token_count = 20

            usage_metadata = UsageMetadata()

        mock_model.generate_content_stream.return_value = [MockResponse1(), MockResponse2()]

        messages: list[MessageParam] = [{"role": "user", "content": "test message"}]
        system = "test system"

        response = list(GeminiProvider(self.model_id).stream_response(system, messages))

        assert len(response) == 2  # One for text chunk, one for usage
        assert response[0] == 'data: {"type": "text", "text": "test response"}\n\n'
        assert response[1] == 'data: {"type": "usage", "input_tokens": 10, "output_tokens": 20}\n\n'

        mock_model.generate_content_stream.assert_called_once()

    @patch("google.genai.Client")
    def test_stream_response_api_error(self, mock_client_class):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_model = Mock()
        mock_client.models = mock_model
        mock_model.generate_content_stream.side_effect = APIError(
            code=400, response_json={"error": {"message": "API Error"}}
        )

        provider = GeminiProvider(self.model_id)
        result = list(provider.stream_response("system prompt", [{"role": "user", "content": "test"}]))

        assert len(result) == 1
        assert result[0] == 'data: {"type": "error", "error": "Gemini API error"}\n\n'

    @patch("google.genai.Client")
    def test_stream_response_unexpected_error(self, mock_client_class):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_model = Mock()
        mock_client.models = mock_model
        mock_model.generate_content_stream.side_effect = Exception("Unexpected error")

        provider = GeminiProvider(self.model_id)
        result = list(provider.stream_response("system prompt", [{"role": "user", "content": "test"}]))

        assert len(result) == 1
        assert result[0] == 'data: {"type": "error", "error": "Unexpected error"}\n\n'
