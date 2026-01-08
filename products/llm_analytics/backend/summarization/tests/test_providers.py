import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from rest_framework import exceptions

from products.llm_analytics.backend.summarization.llm.gemini import summarize_with_gemini
from products.llm_analytics.backend.summarization.llm.openai import summarize_with_openai
from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse
from products.llm_analytics.backend.summarization.models import GeminiModel, OpenAIModel, SummarizationMode


@pytest.fixture
def valid_response_json():
    return json.dumps(
        {
            "title": "Test Summary",
            "flow_diagram": "User → Assistant",
            "summary_bullets": [{"text": "Test bullet", "line_refs": "L1"}],
            "interesting_notes": [],
        }
    )


class TestSummarizeWithOpenAI:
    @pytest.mark.asyncio
    async def test_successful_summarization(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.llm_analytics.backend.summarization.llm.openai.AsyncOpenAI") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

            result = await summarize_with_openai(
                text_repr="L1: Test content",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_4_1_MINI,
            )

            assert isinstance(result, SummarizationResponse)
            assert result.title == "Test Summary"

    @pytest.mark.asyncio
    async def test_empty_response_raises_validation_error(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None

        with patch("products.llm_analytics.backend.summarization.llm.openai.AsyncOpenAI") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

            with pytest.raises(exceptions.ValidationError, match="empty response"):
                await summarize_with_openai(
                    text_repr="L1: Test",
                    team_id=1,
                    mode=SummarizationMode.MINIMAL,
                    model=OpenAIModel.GPT_4_1_MINI,
                )

    @pytest.mark.asyncio
    async def test_api_error_raises_api_exception(self):
        with patch("products.llm_analytics.backend.summarization.llm.openai.AsyncOpenAI") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API Error"))

            with pytest.raises(exceptions.APIException, match="Failed to generate summary"):
                await summarize_with_openai(
                    text_repr="L1: Test",
                    team_id=1,
                    mode=SummarizationMode.MINIMAL,
                    model=OpenAIModel.GPT_4_1_MINI,
                )

    @pytest.mark.asyncio
    async def test_uses_correct_model(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.llm_analytics.backend.summarization.llm.openai.AsyncOpenAI") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

            await summarize_with_openai(
                text_repr="L1: Test",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_4O,
            )

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["model"] == OpenAIModel.GPT_4O

    @pytest.mark.asyncio
    async def test_uses_json_schema_format(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.llm_analytics.backend.summarization.llm.openai.AsyncOpenAI") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

            await summarize_with_openai(
                text_repr="L1: Test",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_4_1_MINI,
            )

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["response_format"]["type"] == "json_schema"
            assert call_kwargs["response_format"]["json_schema"]["strict"] is True


class TestSummarizeWithGemini:
    @pytest.mark.asyncio
    async def test_empty_text_repr_raises_validation_error(self):
        with pytest.raises(exceptions.ValidationError, match="cannot be empty"):
            await summarize_with_gemini(
                text_repr="",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=GeminiModel.GEMINI_3_FLASH_PREVIEW,
            )

    @pytest.mark.asyncio
    async def test_successful_summarization(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.text = valid_response_json

        with (
            patch("products.llm_analytics.backend.summarization.llm.gemini.settings") as mock_settings,
            patch("products.llm_analytics.backend.summarization.llm.gemini.genai") as mock_genai,
        ):
            mock_settings.GEMINI_API_KEY = "test-key"
            mock_client = MagicMock()
            mock_genai.Client.return_value = mock_client
            mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

            result = await summarize_with_gemini(
                text_repr="L1: Test content",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=GeminiModel.GEMINI_3_FLASH_PREVIEW,
            )

            assert isinstance(result, SummarizationResponse)
            assert result.title == "Test Summary"

    @pytest.mark.asyncio
    async def test_empty_response_raises_validation_error(self):
        mock_response = MagicMock()
        mock_response.text = None

        with (
            patch("products.llm_analytics.backend.summarization.llm.gemini.settings") as mock_settings,
            patch("products.llm_analytics.backend.summarization.llm.gemini.genai") as mock_genai,
        ):
            mock_settings.GEMINI_API_KEY = "test-key"
            mock_client = MagicMock()
            mock_genai.Client.return_value = mock_client
            mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

            with pytest.raises(exceptions.ValidationError, match="empty response"):
                await summarize_with_gemini(
                    text_repr="L1: Test",
                    team_id=1,
                    mode=SummarizationMode.MINIMAL,
                    model=GeminiModel.GEMINI_3_FLASH_PREVIEW,
                )

    @pytest.mark.asyncio
    async def test_api_error_raises_api_exception(self):
        with (
            patch("products.llm_analytics.backend.summarization.llm.gemini.settings") as mock_settings,
            patch("products.llm_analytics.backend.summarization.llm.gemini.genai") as mock_genai,
        ):
            mock_settings.GEMINI_API_KEY = "test-key"
            mock_client = MagicMock()
            mock_genai.Client.return_value = mock_client
            mock_client.aio.models.generate_content = AsyncMock(side_effect=Exception("API Error"))

            with pytest.raises(exceptions.APIException, match="Failed to generate summary"):
                await summarize_with_gemini(
                    text_repr="L1: Test",
                    team_id=1,
                    mode=SummarizationMode.MINIMAL,
                    model=GeminiModel.GEMINI_3_FLASH_PREVIEW,
                )

    @pytest.mark.asyncio
    async def test_uses_correct_model(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.text = valid_response_json

        with (
            patch("products.llm_analytics.backend.summarization.llm.gemini.settings") as mock_settings,
            patch("products.llm_analytics.backend.summarization.llm.gemini.genai") as mock_genai,
        ):
            mock_settings.GEMINI_API_KEY = "test-key"
            mock_client = MagicMock()
            mock_genai.Client.return_value = mock_client
            mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

            await summarize_with_gemini(
                text_repr="L1: Test",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=GeminiModel.GEMINI_2_0_FLASH,
            )

            call_kwargs = mock_client.aio.models.generate_content.call_args[1]
            assert call_kwargs["model"] == GeminiModel.GEMINI_2_0_FLASH

    @pytest.mark.asyncio
    async def test_uses_json_schema_config(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.text = valid_response_json

        with (
            patch("products.llm_analytics.backend.summarization.llm.gemini.settings") as mock_settings,
            patch("products.llm_analytics.backend.summarization.llm.gemini.genai") as mock_genai,
        ):
            mock_settings.GEMINI_API_KEY = "test-key"
            mock_client = MagicMock()
            mock_genai.Client.return_value = mock_client
            mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

            await summarize_with_gemini(
                text_repr="L1: Test",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=GeminiModel.GEMINI_3_FLASH_PREVIEW,
            )

            call_kwargs = mock_client.aio.models.generate_content.call_args[1]
            config = call_kwargs["config"]
            assert config.response_mime_type == "application/json"
            assert config.response_json_schema is not None
