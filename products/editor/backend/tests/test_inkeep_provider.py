import json
from unittest.mock import MagicMock, patch

import openai
from django.test import TestCase

from products.editor.backend.providers.inkeep import InkeepProvider


@patch("django.conf.settings.INKEEP_API_KEY", "test_key")
class TestInkeepProvider(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.model_id = "inkeep-qa-expert"

    def test_validate_messages(self):
        provider = InkeepProvider(self.model_id)

        # Valid messages
        valid_messages = [{"role": "user", "content": "test"}]
        provider.validate_messages(valid_messages)  # Should not raise

        # Empty messages
        with self.assertRaises(ValueError) as cm:
            provider.validate_messages([])
        self.assertEqual(str(cm.exception), "Messages list cannot be empty")

        # Missing role
        with self.assertRaises(ValueError) as cm:
            provider.validate_messages([{"content": "test"}])
        self.assertEqual(str(cm.exception), "Each message must contain 'role' and 'content' fields")

        # Missing content
        with self.assertRaises(ValueError) as cm:
            provider.validate_messages([{"role": "user"}])
        self.assertEqual(str(cm.exception), "Each message must contain 'role' and 'content' fields")

    @patch("openai.OpenAI")
    def test_stream_response_success(self, mock_openai):
        provider = InkeepProvider(self.model_id)
        mock_stream = MagicMock()
        mock_openai.return_value.chat.completions.create.return_value = mock_stream

        # Mock stream chunks
        mock_stream.__iter__.return_value = [
            MagicMock(choices=[MagicMock(delta=MagicMock(content="First chunk"))], usage=None),
            MagicMock(
                choices=[MagicMock(delta=MagicMock(content=" Second chunk"))],
                usage=MagicMock(prompt_tokens=10, completion_tokens=5),
            ),
        ]

        messages = [{"role": "user", "content": "test"}]
        response_stream = provider.stream_response("", messages)
        responses = list(response_stream)

        # Verify the responses
        self.assertEqual(json.loads(responses[0].split("data: ")[1]), {"type": "text", "text": "First chunk"})
        self.assertEqual(json.loads(responses[1].split("data: ")[1]), {"type": "text", "text": " Second chunk"})
        self.assertEqual(
            json.loads(responses[2].split("data: ")[1]), {"type": "usage", "input_tokens": 10, "output_tokens": 5}
        )

        # Verify OpenAI client was called with correct parameters
        mock_openai.return_value.chat.completions.create.assert_called_once_with(
            model=self.model_id, stream=True, messages=messages, stream_options={"include_usage": True}
        )

    @patch("openai.OpenAI")
    def test_stream_response_api_error(self, mock_openai):
        provider = InkeepProvider(self.model_id)
        mock_openai.return_value.chat.completions.create.side_effect = openai.APIError(
            message="API Error", request=MagicMock(), body={"error": "test error"}
        )

        messages = [{"role": "user", "content": "test"}]
        response_stream = provider.stream_response("", messages)
        responses = list(response_stream)

        self.assertEqual(len(responses), 1)
        error_response = json.loads(responses[0].split("data: ")[1])
        self.assertEqual(error_response["type"], "error")
        self.assertEqual(error_response["error"], "Inkeep API error")

    @patch("openai.OpenAI")
    def test_stream_response_unexpected_error(self, mock_openai):
        provider = InkeepProvider(self.model_id)
        mock_openai.return_value.chat.completions.create.side_effect = Exception("Unexpected Error")

        messages = [{"role": "user", "content": "test"}]
        response_stream = provider.stream_response("", messages)
        responses = list(response_stream)

        self.assertEqual(len(responses), 1)
        error_response = json.loads(responses[0].split("data: ")[1])
        self.assertEqual(error_response["type"], "error")
        self.assertEqual(error_response["error"], "Unexpected error")

    @patch("openai.OpenAI")
    def test_stream_response_empty_response(self, mock_openai):
        provider = InkeepProvider(self.model_id)
        mock_stream = MagicMock()
        mock_openai.return_value.chat.completions.create.return_value = mock_stream

        # Mock empty stream
        mock_stream.__iter__.return_value = []

        messages = [{"role": "user", "content": "test"}]
        response_stream = provider.stream_response("", messages)
        responses = list(response_stream)

        # Verify no responses were generated
        self.assertEqual(len(responses), 0)

        # Verify OpenAI client was still called with correct parameters
        mock_openai.return_value.chat.completions.create.assert_called_once_with(
            model=self.model_id, stream=True, messages=messages, stream_options={"include_usage": True}
        )

    @patch("openai.OpenAI")
    def test_stream_response_ignores_thinking_param(self, mock_openai):
        provider = InkeepProvider(self.model_id)
        mock_stream = MagicMock()
        mock_openai.return_value.chat.completions.create.return_value = mock_stream
        mock_stream.__iter__.return_value = []

        messages = [{"role": "user", "content": "test"}]
        response_stream = provider.stream_response("", messages, thinking=True)
        list(response_stream)  # Consume the stream

        # Verify thinking parameter was ignored
        mock_openai.return_value.chat.completions.create.assert_called_once_with(
            model=self.model_id, stream=True, messages=messages, stream_options={"include_usage": True}
        )
