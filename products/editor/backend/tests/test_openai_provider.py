from unittest.mock import patch, MagicMock
import pytest
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletion, ChatCompletionMessage, ChatCompletionChunk
from django.test import TestCase, override_settings
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_chunk import Choice as ChunkChoice, ChoiceDelta
from openai._exceptions import APIError

from products.editor.backend.providers.openai import OpenAIProvider


class TestOpenAIProvider(TestCase):
    def setUp(self):
        self.model_id = "gpt-4o"

    def test_validate_model(self):
        OpenAIProvider(self.model_id)
        with pytest.raises(ValueError, match="Model invalid-model is not supported"):
            OpenAIProvider("invalid-model")

    @override_settings(OPENAI_API_KEY="test-key")
    def test_yield_usage(self):
        provider = OpenAIProvider(self.model_id)
        usage = CompletionUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)

        result = list(provider.yield_usage(usage))
        assert len(result) == 1
        assert '"input_tokens": 10' in result[0]
        assert '"output_tokens": 20' in result[0]
        assert '"cache_read_tokens": 0' in result[0]
        assert '"cache_write_tokens": 0' in result[0]

    @patch("openai.OpenAI")
    @override_settings(OPENAI_API_KEY="test-key")
    def test_stream_response_o1_model(self, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        mock_response = ChatCompletion(
            id="test",
            choices=[
                Choice(
                    message=ChatCompletionMessage(content="Test response", role="assistant"),
                    finish_reason="stop",
                    index=0,
                    logprobs=None,
                )
            ],
            model="o1",
            object="chat.completion",
            created=123,
            usage=CompletionUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )
        mock_client.chat.completions.create.return_value = mock_response

        provider = OpenAIProvider("o1")
        result = list(provider.stream_response("system prompt", [{"role": "user", "content": "test"}]))

        assert len(result) == 2
        assert result[0] == 'data: {"type": "text", "text": "Test response"}\n\n'
        assert (
            result[1]
            == 'data: {"type": "usage", "input_tokens": 10, "output_tokens": 20, "cache_read_tokens": 0, "cache_write_tokens": 0}\n\n'
        )

    @patch("openai.OpenAI")
    @override_settings(OPENAI_API_KEY="test-key")
    def test_stream_response_o3_model(self, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        mock_chunks = [
            ChatCompletionChunk(
                id="test",
                choices=[
                    ChunkChoice(delta=ChoiceDelta(content="Test ", role="assistant"), finish_reason=None, index=0)
                ],
                model="o3-mini",
                object="chat.completion.chunk",
                created=123,
            ),
            ChatCompletionChunk(
                id="test",
                choices=[
                    ChunkChoice(delta=ChoiceDelta(content="response", role="assistant"), finish_reason="stop", index=0)
                ],
                model="o3-mini",
                object="chat.completion.chunk",
                created=123,
                usage=CompletionUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
            ),
        ]
        mock_client.chat.completions.create.return_value = mock_chunks

        provider = OpenAIProvider("o3-mini")
        result = list(provider.stream_response("system prompt", [{"role": "user", "content": "test"}], thinking=True))

        assert len(result) == 3
        assert result[0] == 'data: {"type": "text", "text": "Test "}\n\n'
        assert result[1] == 'data: {"type": "text", "text": "response"}\n\n'
        assert (
            result[2]
            == 'data: {"type": "usage", "input_tokens": 10, "output_tokens": 20, "cache_read_tokens": 0, "cache_write_tokens": 0}\n\n'
        )

    @patch("openai.OpenAI")
    @override_settings(OPENAI_API_KEY="test-key")
    def test_stream_response_api_error(self, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.side_effect = APIError(message="API Error", request=MagicMock(), body=None)

        provider = OpenAIProvider(self.model_id)
        result = list(provider.stream_response("system prompt", [{"role": "user", "content": "test"}]))

        assert len(result) == 1
        assert result[0] == 'data: {"type": "error", "error": "OpenAI API error"}\n\n'

    @patch("openai.OpenAI")
    @override_settings(OPENAI_API_KEY="test-key")
    def test_stream_response_unexpected_error(self, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("Unexpected error")

        provider = OpenAIProvider(self.model_id)
        result = list(provider.stream_response("system prompt", [{"role": "user", "content": "test"}]))

        assert len(result) == 1
        assert result[0] == 'data: {"type": "error", "error": "Unexpected error"}\n\n'
