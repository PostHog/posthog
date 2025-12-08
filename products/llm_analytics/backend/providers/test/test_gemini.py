import json
from typing import cast

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, PropertyMock, patch

from django.test import override_settings

from anthropic.types import MessageParam
from google.genai.errors import APIError
from parameterized import parameterized

from products.llm_analytics.backend.providers.gemini import GeminiConfig, GeminiProvider


class TestGeminiConfig(BaseTest):
    def test_default_temperature(self):
        assert GeminiConfig.TEMPERATURE == 0

    def test_supported_models(self):
        supported_models = [
            "gemini-2.5-flash-preview-09-2025",
            "gemini-2.5-flash-lite-preview-09-2025",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ]
        for model in supported_models:
            assert model in GeminiConfig.SUPPORTED_MODELS


class TestGeminiProvider(BaseTest):
    @override_settings(GEMINI_API_KEY="test-api-key")
    @patch("products.llm_analytics.backend.providers.gemini.genai.Client")
    @patch("posthoganalytics.default_client")
    def test_provider_initialization(self, mock_posthog_client, mock_genai_client):
        mock_posthog_client.return_value = MagicMock()

        provider = GeminiProvider("gemini-2.0-flash")

        assert provider.model_id == "gemini-2.0-flash"
        mock_genai_client.assert_called_once_with(api_key="test-api-key", posthog_client=mock_posthog_client)

    @override_settings(GEMINI_API_KEY=None)
    def test_missing_api_key_raises_error(self):
        with pytest.raises(ValueError, match="GEMINI_API_KEY is not set"):
            GeminiProvider.get_api_key()

    @override_settings(GEMINI_API_KEY="test-api-key")
    @patch("posthoganalytics.default_client", None)
    def test_missing_posthog_client_raises_error(self):
        with pytest.raises(ValueError, match="PostHog client not found"):
            GeminiProvider("gemini-2.0-flash")

    @override_settings(GEMINI_API_KEY="test-api-key")
    @patch("products.llm_analytics.backend.providers.gemini.genai.Client")
    @patch("posthoganalytics.default_client")
    def test_invalid_model_raises_error(self, mock_posthog_client, mock_genai_client):
        mock_posthog_client.return_value = MagicMock()

        with pytest.raises(ValueError, match="Model invalid-model is not supported"):
            GeminiProvider("invalid-model")


class TestGeminiStreamResponse(BaseTest):
    def setUp(self):
        super().setUp()
        self.mock_posthog_client = MagicMock()
        self.mock_genai_client = MagicMock()
        self.messages = cast(list[MessageParam], [{"role": "user", "content": "Test message"}])

    @override_settings(GEMINI_API_KEY="test-api-key")
    @patch("products.llm_analytics.backend.providers.gemini.genai.Client")
    @patch("posthoganalytics.default_client")
    def test_basic_text_streaming(self, mock_posthog, mock_genai):
        mock_posthog.return_value = self.mock_posthog_client
        mock_genai.return_value = self.mock_genai_client

        def mock_stream():
            mock_chunk1 = MagicMock()
            mock_chunk1.text = "Hello "
            mock_chunk1.candidates = None
            mock_chunk1.usage_metadata = None

            mock_chunk2 = MagicMock()
            mock_chunk2.text = "world!"
            mock_chunk2.candidates = None
            mock_chunk2.usage_metadata = None

            yield mock_chunk1
            yield mock_chunk2

        self.mock_genai_client.models.generate_content_stream.return_value = mock_stream()

        provider = GeminiProvider("gemini-2.0-flash")
        response = provider.stream_response(system="Be helpful", messages=self.messages, distinct_id="test-user")

        responses = list(response)

        assert len(responses) == 2
        assert json.loads(responses[0].replace("data: ", "").strip()) == {"type": "text", "text": "Hello "}
        assert json.loads(responses[1].replace("data: ", "").strip()) == {"type": "text", "text": "world!"}

    @override_settings(GEMINI_API_KEY="test-api-key")
    @patch("products.llm_analytics.backend.providers.gemini.genai.Client")
    @patch("posthoganalytics.default_client")
    def test_streaming_with_none_parts(self, mock_posthog, mock_genai):
        mock_posthog.return_value = self.mock_posthog_client
        mock_genai.return_value = self.mock_genai_client

        def mock_stream():
            mock_chunk = MagicMock()
            mock_chunk.text = "Test text"

            mock_candidate = MagicMock()
            mock_content = MagicMock()
            mock_content.parts = None  # Bug condition
            mock_candidate.content = mock_content

            mock_chunk.candidates = [mock_candidate]
            mock_chunk.usage_metadata = None

            yield mock_chunk

        self.mock_genai_client.models.generate_content_stream.return_value = mock_stream()

        provider = GeminiProvider("gemini-2.0-flash")
        response = provider.stream_response(system="Be helpful", messages=self.messages, distinct_id="test-user")

        responses = list(response)
        assert len(responses) == 1
        assert json.loads(responses[0].replace("data: ", "").strip()) == {"type": "text", "text": "Test text"}

    @override_settings(GEMINI_API_KEY="test-api-key")
    @patch("products.llm_analytics.backend.providers.gemini.genai.Client")
    @patch("posthoganalytics.default_client")
    def test_streaming_with_empty_parts(self, mock_posthog, mock_genai):
        mock_posthog.return_value = self.mock_posthog_client
        mock_genai.return_value = self.mock_genai_client

        def mock_stream():
            mock_chunk = MagicMock()
            mock_chunk.text = None

            mock_candidate = MagicMock()
            mock_content = MagicMock()
            mock_content.parts = []
            mock_candidate.content = mock_content

            mock_chunk.candidates = [mock_candidate]
            mock_chunk.usage_metadata = None

            yield mock_chunk

        self.mock_genai_client.models.generate_content_stream.return_value = mock_stream()

        provider = GeminiProvider("gemini-2.0-flash")
        response = provider.stream_response(system="Be helpful", messages=self.messages, distinct_id="test-user")

        responses = list(response)
        assert len(responses) == 0

    @override_settings(GEMINI_API_KEY="test-api-key")
    @patch("products.llm_analytics.backend.providers.gemini.genai.Client")
    @patch("posthoganalytics.default_client")
    def test_streaming_with_function_calls(self, mock_posthog, mock_genai):
        mock_posthog.return_value = self.mock_posthog_client
        mock_genai.return_value = self.mock_genai_client

        def mock_stream():
            mock_chunk = MagicMock()
            mock_chunk.text = None

            mock_function_call = MagicMock()
            mock_function_call.name = "get_weather"
            mock_function_call.args = {"location": "San Francisco"}

            mock_part = MagicMock()
            mock_part.function_call = mock_function_call
            type(mock_part).function_call = PropertyMock(return_value=mock_function_call)
            del mock_part.text

            mock_content = MagicMock()
            mock_content.parts = [mock_part]

            mock_candidate = MagicMock()
            mock_candidate.content = mock_content

            mock_chunk.candidates = [mock_candidate]
            mock_chunk.usage_metadata = None

            yield mock_chunk

        self.mock_genai_client.models.generate_content_stream.return_value = mock_stream()

        provider = GeminiProvider("gemini-2.0-flash")
        response = provider.stream_response(
            system="Be helpful",
            messages=self.messages,
            distinct_id="test-user",
            tools=[
                {"functionDeclarations": [{"name": "get_weather", "parameters": {"type": "object", "properties": {}}}]}
            ],
        )

        responses = list(response)
        assert len(responses) == 1

        tool_response = json.loads(responses[0].replace("data: ", "").strip())
        assert tool_response["type"] == "tool_call"
        assert tool_response["function"]["name"] == "get_weather"
        assert json.loads(tool_response["function"]["arguments"]) == {"location": "San Francisco"}

    @override_settings(GEMINI_API_KEY="test-api-key")
    @patch("products.llm_analytics.backend.providers.gemini.genai.Client")
    @patch("posthoganalytics.default_client")
    def test_streaming_with_text_in_parts(self, mock_posthog, mock_genai):
        mock_posthog.return_value = self.mock_posthog_client
        mock_genai.return_value = self.mock_genai_client

        def mock_stream():
            mock_chunk = MagicMock()
            mock_chunk.text = None

            mock_part = MagicMock()
            mock_part.text = "Text from parts"
            type(mock_part).text = PropertyMock(return_value="Text from parts")
            del mock_part.function_call

            mock_content = MagicMock()
            mock_content.parts = [mock_part]

            mock_candidate = MagicMock()
            mock_candidate.content = mock_content

            mock_chunk.candidates = [mock_candidate]
            mock_chunk.usage_metadata = None

            yield mock_chunk

        self.mock_genai_client.models.generate_content_stream.return_value = mock_stream()

        provider = GeminiProvider("gemini-2.0-flash")
        response = provider.stream_response(system="Be helpful", messages=self.messages, distinct_id="test-user")

        responses = list(response)
        assert len(responses) == 1
        assert json.loads(responses[0].replace("data: ", "").strip()) == {"type": "text", "text": "Text from parts"}

    @override_settings(GEMINI_API_KEY="test-api-key")
    @patch("products.llm_analytics.backend.providers.gemini.genai.Client")
    @patch("posthoganalytics.default_client")
    def test_streaming_with_mixed_parts(self, mock_posthog, mock_genai):
        mock_posthog.return_value = self.mock_posthog_client
        mock_genai.return_value = self.mock_genai_client

        def mock_stream():
            mock_chunk = MagicMock()
            mock_chunk.text = None

            mock_text_part = MagicMock()
            mock_text_part.text = "Let me check the weather"
            type(mock_text_part).text = PropertyMock(return_value="Let me check the weather")
            del mock_text_part.function_call

            mock_function_call = MagicMock()
            mock_function_call.name = "get_weather"
            mock_function_call.args = {"location": "NYC"}

            mock_function_part = MagicMock()
            mock_function_part.function_call = mock_function_call
            type(mock_function_part).function_call = PropertyMock(return_value=mock_function_call)
            del mock_function_part.text

            mock_content = MagicMock()
            mock_content.parts = [mock_text_part, mock_function_part]

            mock_candidate = MagicMock()
            mock_candidate.content = mock_content

            mock_chunk.candidates = [mock_candidate]
            mock_chunk.usage_metadata = None

            yield mock_chunk

        self.mock_genai_client.models.generate_content_stream.return_value = mock_stream()

        provider = GeminiProvider("gemini-2.0-flash")
        response = provider.stream_response(system="Be helpful", messages=self.messages, distinct_id="test-user")

        responses = list(response)
        assert len(responses) == 2

        assert json.loads(responses[0].replace("data: ", "").strip()) == {
            "type": "text",
            "text": "Let me check the weather",
        }

        tool_response = json.loads(responses[1].replace("data: ", "").strip())
        assert tool_response["type"] == "tool_call"
        assert tool_response["function"]["name"] == "get_weather"

    @override_settings(GEMINI_API_KEY="test-api-key")
    @patch("products.llm_analytics.backend.providers.gemini.genai.Client")
    @patch("posthoganalytics.default_client")
    def test_streaming_with_usage_metadata(self, mock_posthog, mock_genai):
        mock_posthog.return_value = self.mock_posthog_client
        mock_genai.return_value = self.mock_genai_client

        def mock_stream():
            mock_chunk = MagicMock()
            mock_chunk.text = "Response text"
            mock_chunk.candidates = None

            mock_usage = MagicMock()
            mock_usage.prompt_token_count = 10
            mock_usage.candidates_token_count = 5
            mock_chunk.usage_metadata = mock_usage

            yield mock_chunk

        self.mock_genai_client.models.generate_content_stream.return_value = mock_stream()

        provider = GeminiProvider("gemini-2.0-flash")
        response = provider.stream_response(system="Be helpful", messages=self.messages, distinct_id="test-user")

        responses = list(response)
        assert len(responses) == 2

        assert json.loads(responses[0].replace("data: ", "").strip()) == {"type": "text", "text": "Response text"}

        usage_response = json.loads(responses[1].replace("data: ", "").strip())
        assert usage_response == {"type": "usage", "input_tokens": 10, "output_tokens": 5}


class TestGeminiErrorHandling(BaseTest):
    def setUp(self):
        super().setUp()
        self.mock_posthog_client = MagicMock()
        self.mock_genai_client = MagicMock()
        self.messages = cast(list[MessageParam], [{"role": "user", "content": "Test message"}])

    @override_settings(GEMINI_API_KEY="test-api-key")
    @patch("products.llm_analytics.backend.providers.gemini.genai.Client")
    @patch("posthoganalytics.default_client")
    def test_api_error_handling(self, mock_posthog, mock_genai):
        mock_posthog.return_value = self.mock_posthog_client
        mock_genai.return_value = self.mock_genai_client

        self.mock_genai_client.models.generate_content_stream.side_effect = APIError(
            400, {"message": "API rate limit exceeded"}, None
        )

        provider = GeminiProvider("gemini-2.0-flash")
        response = provider.stream_response(system="Be helpful", messages=self.messages, distinct_id="test-user")

        responses = list(response)
        assert len(responses) == 1

        error_response = json.loads(responses[0].replace("data: ", "").strip())
        assert error_response["type"] == "error"
        assert error_response["error"] == "Gemini API error"

    @override_settings(GEMINI_API_KEY="test-api-key")
    @patch("products.llm_analytics.backend.providers.gemini.genai.Client")
    @patch("posthoganalytics.default_client")
    def test_generic_exception_handling(self, mock_posthog, mock_genai):
        mock_posthog.return_value = self.mock_posthog_client
        mock_genai.return_value = self.mock_genai_client

        self.mock_genai_client.models.generate_content_stream.side_effect = Exception("Unexpected error occurred")

        provider = GeminiProvider("gemini-2.0-flash")
        response = provider.stream_response(system="Be helpful", messages=self.messages, distinct_id="test-user")

        responses = list(response)
        assert len(responses) == 1

        error_response = json.loads(responses[0].replace("data: ", "").strip())
        assert error_response["type"] == "error"
        assert error_response["error"] == "Unexpected error"

    @override_settings(GEMINI_API_KEY="test-api-key")
    @patch("products.llm_analytics.backend.providers.gemini.genai.Client")
    @patch("posthoganalytics.default_client")
    def test_missing_candidates_attribute(self, mock_posthog, mock_genai):
        mock_posthog.return_value = self.mock_posthog_client
        mock_genai.return_value = self.mock_genai_client

        def mock_stream():
            mock_chunk = MagicMock()
            mock_chunk.text = "Text response"
            del mock_chunk.candidates
            mock_chunk.usage_metadata = None

            yield mock_chunk

        self.mock_genai_client.models.generate_content_stream.return_value = mock_stream()

        provider = GeminiProvider("gemini-2.0-flash")
        response = provider.stream_response(system="Be helpful", messages=self.messages, distinct_id="test-user")

        responses = list(response)
        assert len(responses) == 1
        assert json.loads(responses[0].replace("data: ", "").strip()) == {"type": "text", "text": "Text response"}

    @override_settings(GEMINI_API_KEY="test-api-key")
    @patch("products.llm_analytics.backend.providers.gemini.genai.Client")
    @patch("posthoganalytics.default_client")
    def test_candidate_without_content(self, mock_posthog, mock_genai):
        mock_posthog.return_value = self.mock_posthog_client
        mock_genai.return_value = self.mock_genai_client

        def mock_stream():
            mock_chunk = MagicMock()
            mock_chunk.text = None

            mock_candidate = MagicMock()
            mock_candidate.content = None

            mock_chunk.candidates = [mock_candidate]
            mock_chunk.usage_metadata = None

            yield mock_chunk

        self.mock_genai_client.models.generate_content_stream.return_value = mock_stream()

        provider = GeminiProvider("gemini-2.0-flash")
        response = provider.stream_response(system="Be helpful", messages=self.messages, distinct_id="test-user")

        responses = list(response)
        assert len(responses) == 0


class TestGeminiIntegration(BaseTest):
    @override_settings(GEMINI_API_KEY="test-api-key")
    @patch("products.llm_analytics.backend.providers.gemini.genai.Client")
    @patch("posthoganalytics.default_client")
    @patch("products.llm_analytics.backend.providers.gemini.uuid.uuid4")
    def test_trace_id_generation(self, mock_uuid, mock_posthog, mock_genai):
        mock_posthog.return_value = MagicMock()
        mock_genai.return_value = MagicMock()

        test_uuid = "test-trace-id-123"
        mock_uuid.return_value = test_uuid

        def mock_stream():
            mock_chunk = MagicMock()
            mock_chunk.text = "Response"
            mock_chunk.candidates = None
            mock_chunk.usage_metadata = None
            yield mock_chunk

        mock_genai.return_value.models.generate_content_stream.return_value = mock_stream()

        provider = GeminiProvider("gemini-2.0-flash")
        response = provider.stream_response(
            system="Be helpful",
            messages=cast(list[MessageParam], [{"role": "user", "content": "Test"}]),
            distinct_id="test-user",
            trace_id=None,
        )

        list(response)

        call_kwargs = mock_genai.return_value.models.generate_content_stream.call_args[1]
        assert call_kwargs["posthog_trace_id"] == test_uuid

    @override_settings(GEMINI_API_KEY="test-api-key")
    @patch("products.llm_analytics.backend.providers.gemini.genai.Client")
    @patch("posthoganalytics.default_client")
    def test_properties_include_ai_product(self, mock_posthog, mock_genai):
        mock_posthog.return_value = MagicMock()
        mock_genai.return_value = MagicMock()

        def mock_stream():
            mock_chunk = MagicMock()
            mock_chunk.text = "Response"
            mock_chunk.candidates = None
            mock_chunk.usage_metadata = None
            yield mock_chunk

        mock_genai.return_value.models.generate_content_stream.return_value = mock_stream()

        provider = GeminiProvider("gemini-2.0-flash")
        response = provider.stream_response(
            system="Be helpful",
            messages=cast(list[MessageParam], [{"role": "user", "content": "Test"}]),
            distinct_id="test-user",
            properties={"custom": "property"},
        )

        list(response)

        call_kwargs = mock_genai.return_value.models.generate_content_stream.call_args[1]
        assert call_kwargs["posthog_properties"] == {"custom": "property", "ai_product": "playground"}

    @parameterized.expand(
        [
            (None, None, 0, None),
            (0.5, None, 0.5, None),
            (None, 1000, 0, 1000),
            (0.7, 2000, 0.7, 2000),
        ]
    )
    @override_settings(GEMINI_API_KEY="test-api-key")
    @patch("products.llm_analytics.backend.providers.gemini.genai.Client")
    @patch("posthoganalytics.default_client")
    def test_temperature_and_max_tokens_handling(
        self, input_temp, input_max_tokens, expected_temp, expected_max_tokens, mock_posthog, mock_genai
    ):
        mock_posthog.return_value = MagicMock()
        mock_genai.return_value = MagicMock()

        def mock_stream():
            mock_chunk = MagicMock()
            mock_chunk.text = "Response"
            mock_chunk.candidates = None
            mock_chunk.usage_metadata = None
            yield mock_chunk

        mock_genai.return_value.models.generate_content_stream.return_value = mock_stream()

        provider = GeminiProvider("gemini-2.0-flash")
        response = provider.stream_response(
            system="Be helpful",
            messages=cast(list[MessageParam], [{"role": "user", "content": "Test"}]),
            distinct_id="test-user",
            temperature=input_temp,
            max_tokens=input_max_tokens,
        )

        list(response)

        call_args = mock_genai.return_value.models.generate_content_stream.call_args[1]
        config = call_args["config"]

        assert config.temperature == expected_temp
        if expected_max_tokens is not None:
            assert config.max_output_tokens == expected_max_tokens
        else:
            assert config.max_output_tokens is None
