import json

import pytest
from unittest.mock import MagicMock, patch

from rest_framework import exceptions

from products.llm_analytics.backend.summarization.llm.openai import summarize_with_openai
from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse
from products.llm_analytics.backend.summarization.models import OpenAIModel, SummarizationMode


@pytest.fixture
def valid_response_json():
    return json.dumps(
        {
            "title": "Test Summary",
            "flow_diagram": "User -> Assistant",
            "summary_bullets": [{"text": "Test bullet", "line_refs": "L1"}],
            "interesting_notes": [],
        }
    )


class TestSummarizeWithOpenAI:
    def test_successful_summarization(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.llm_analytics.backend.summarization.llm.openai.get_llm_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            result = summarize_with_openai(
                text_repr="L1: Test content",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_4_1_MINI,
            )

            assert isinstance(result, SummarizationResponse)
            assert result.title == "Test Summary"
            mock_get_client.assert_called_once_with("llma_summarization")

    def test_empty_response_raises_validation_error(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None

        with patch("products.llm_analytics.backend.summarization.llm.openai.get_llm_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            with pytest.raises(exceptions.ValidationError, match="empty response"):
                summarize_with_openai(
                    text_repr="L1: Test",
                    team_id=1,
                    mode=SummarizationMode.MINIMAL,
                    model=OpenAIModel.GPT_4_1_MINI,
                )

    def test_api_error_raises_api_exception(self):
        with patch("products.llm_analytics.backend.summarization.llm.openai.get_llm_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.side_effect = Exception("API Error")

            with pytest.raises(exceptions.APIException, match="Failed to generate summary"):
                summarize_with_openai(
                    text_repr="L1: Test",
                    team_id=1,
                    mode=SummarizationMode.MINIMAL,
                    model=OpenAIModel.GPT_4_1_MINI,
                )

    def test_uses_correct_model(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.llm_analytics.backend.summarization.llm.openai.get_llm_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            summarize_with_openai(
                text_repr="L1: Test",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_4_1_MINI,
            )

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["model"] == OpenAIModel.GPT_4_1_MINI

    def test_uses_user_id_when_provided(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.llm_analytics.backend.summarization.llm.openai.get_llm_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            summarize_with_openai(
                text_repr="L1: Test",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_4_1_MINI,
                user_id="user-distinct-123",
            )

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["user"] == "user-distinct-123"

    def test_uses_team_fallback_when_no_user_id(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.llm_analytics.backend.summarization.llm.openai.get_llm_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            summarize_with_openai(
                text_repr="L1: Test",
                team_id=42,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_4_1_MINI,
            )

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["user"] == "team-42"

    def test_uses_json_schema_format(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.llm_analytics.backend.summarization.llm.openai.get_llm_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            summarize_with_openai(
                text_repr="L1: Test",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_4_1_MINI,
            )

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["response_format"]["type"] == "json_schema"
            assert call_kwargs["response_format"]["json_schema"]["strict"] is True
