"""Tests for survey summarization module."""

import json

import pytest
from unittest.mock import MagicMock, patch

from rest_framework import exceptions

from .constants import SUMMARIZATION_TIMEOUT
from .formatting import format_as_markdown
from .llm.gateway import SummarizationResult, summarize_with_gateway
from .llm.schema import SurveySummaryResponse, SurveyTheme


class TestSurveyThemeSchema:
    """Pydantic validation ensures LLM output conforms to expected structure."""

    @pytest.mark.parametrize("frequency", [">50%", "25-50%", "10-25%", "<10%"])
    def test_valid_frequencies(self, frequency):
        theme = SurveyTheme(theme="Test", description="Desc", frequency=frequency)
        assert theme.frequency == frequency

    def test_rejects_invalid_frequency(self):
        with pytest.raises(ValueError):
            SurveyTheme(theme="Test", description="Desc", frequency="common")


class TestSurveySummaryResponseSchema:
    """Schema constraints prevent malformed summaries."""

    def test_requires_at_least_one_theme(self):
        with pytest.raises(ValueError):
            SurveySummaryResponse(overview="Test", themes=[], key_insight="Test")

    def test_max_five_themes(self):
        themes = [SurveyTheme(theme=f"T{i}", description="D", frequency=">50%") for i in range(6)]
        with pytest.raises(ValueError):
            SurveySummaryResponse(overview="Test", themes=themes, key_insight="Test")


class TestFormatAsMarkdown:
    """Markdown formatting produces readable output."""

    def test_includes_all_sections(self):
        summary = SurveySummaryResponse(
            overview="Users love the product.",
            themes=[
                SurveyTheme(theme="Performance", description="Fast loading", frequency=">50%"),
                SurveyTheme(theme="UI", description="Clean design", frequency="<10%"),
            ],
            key_insight="Keep it fast.",
        )
        result = format_as_markdown(summary)

        assert "Users love the product" in result
        assert "**Performance** (>50%)" in result
        assert "**UI** (<10%)" in result
        assert "Keep it fast" in result

    def test_formats_frequency_percentages(self):
        summary = SurveySummaryResponse(
            overview="Overview",
            themes=[
                SurveyTheme(theme="Theme1", description="Desc1", frequency=">50%"),
                SurveyTheme(theme="Theme2", description="Desc2", frequency="25-50%"),
                SurveyTheme(theme="Theme3", description="Desc3", frequency="10-25%"),
                SurveyTheme(theme="Theme4", description="Desc4", frequency="<10%"),
            ],
            key_insight="Insight",
        )
        result = format_as_markdown(summary)

        assert "(>50%)" in result
        assert "(25-50%)" in result
        assert "(10-25%)" in result
        assert "(<10%)" in result


VALID_SUMMARY = {
    "overview": "Users want better performance",
    "themes": [{"theme": "Speed", "description": "Fast loading times", "frequency": ">50%"}],
    "key_insight": "Focus on performance",
}


def _gateway_response(content: str | None) -> MagicMock:
    """An OpenAI-shaped chat completion as the gateway returns it."""
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _mock_client(mock_get_client: MagicMock) -> MagicMock:
    """Wire the client so `.with_options(...)` returns the same mock the helper uses."""
    client = mock_get_client.return_value
    client.with_options.return_value = client
    return client


class TestSummarizeWithGateway:
    """Error handling for edge cases and API failures."""

    def test_empty_responses_rejected_before_api_call(self):
        with pytest.raises(exceptions.ValidationError) as exc_info:
            summarize_with_gateway("Question", [])
        assert "responses cannot be empty" in str(exc_info.value.detail)

    @patch("products.surveys.backend.llm.gateway.get_llm_client")
    def test_empty_api_response_raises_error(self, mock_get_client):
        _mock_client(mock_get_client).chat.completions.create.return_value = _gateway_response(None)

        with pytest.raises(exceptions.ValidationError) as exc_info:
            summarize_with_gateway("Question", ["Response"])
        assert "empty response" in str(exc_info.value.detail)

    @patch("products.surveys.backend.llm.gateway.get_llm_client")
    def test_api_error_wrapped_as_api_exception(self, mock_get_client):
        _mock_client(mock_get_client).chat.completions.create.side_effect = Exception("API Error")

        with pytest.raises(exceptions.APIException) as exc_info:
            summarize_with_gateway("Question", ["Response"])
        assert "Failed to generate response" in str(exc_info.value.detail)

    @patch("products.surveys.backend.llm.gateway.get_llm_client")
    def test_returns_summarization_result_with_trace_id(self, mock_get_client):
        _mock_client(mock_get_client).chat.completions.create.return_value = _gateway_response(
            json.dumps(VALID_SUMMARY)
        )

        result = summarize_with_gateway("What do you want?", ["Make it faster"])

        assert isinstance(result, SummarizationResult)
        assert isinstance(result.summary, SurveySummaryResponse)
        assert result.trace_id is not None
        assert len(result.trace_id) == 36  # UUID format

    @patch("products.surveys.backend.llm.gateway.get_llm_client")
    def test_routes_through_survey_summary_product_on_haiku(self, mock_get_client):
        _mock_client(mock_get_client).chat.completions.create.return_value = _gateway_response(
            json.dumps(VALID_SUMMARY)
        )

        summarize_with_gateway("What do you want?", ["Make it faster"], team_id=42)

        # The product route drives both the `ai_product` tag and the AI-credits
        # bucket, and the model must stay inside that product's allowlist.
        mock_get_client.assert_called_once_with("survey_summary", team_id=42)
        assert mock_get_client.return_value.chat.completions.create.call_args.kwargs["model"] == "claude-haiku-4-5"

    @patch("products.surveys.backend.llm.gateway.get_llm_client")
    def test_gateway_owned_properties_are_not_sent_by_caller(self, mock_get_client):
        _mock_client(mock_get_client).chat.completions.create.return_value = _gateway_response(
            json.dumps(VALID_SUMMARY)
        )

        summarize_with_gateway("What do you want?", ["Make it faster"], team_id=42)

        headers = mock_get_client.return_value.chat.completions.create.call_args.kwargs["extra_headers"]
        assert "x-posthog-property-ai_product" not in headers
        assert "x-posthog-property-$ai_billable" not in headers
        assert headers["x-posthog-property-ai_feature"] == "survey_summary"
        assert headers["x-posthog-property-response_count"] == "1"

    @patch("products.surveys.backend.llm.gateway.get_llm_client")
    def test_bounds_the_call_with_the_summarization_timeout(self, mock_get_client):
        _mock_client(mock_get_client).chat.completions.create.return_value = _gateway_response(
            json.dumps(VALID_SUMMARY)
        )

        summarize_with_gateway("What do you want?", ["Make it faster"])

        # Runs inline on a DRF worker; unbounded it inherits the SDK's 600s default.
        assert mock_get_client.return_value.chat.completions.create.call_args.kwargs["timeout"] == SUMMARIZATION_TIMEOUT

    @patch("products.surveys.backend.llm.gateway.get_llm_client")
    def test_omits_optional_ids_rather_than_sending_the_string_none(self, mock_get_client):
        _mock_client(mock_get_client).chat.completions.create.return_value = _gateway_response(
            json.dumps(VALID_SUMMARY)
        )

        summarize_with_gateway("What do you want?", ["Make it faster"], survey_id=None, question_id=None)

        headers = mock_get_client.return_value.chat.completions.create.call_args.kwargs["extra_headers"]
        assert "x-posthog-property-survey_id" not in headers
        assert "x-posthog-property-question_id" not in headers
