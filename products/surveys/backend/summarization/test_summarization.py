"""Tests for survey summarization module."""

import pytest
from unittest.mock import MagicMock, patch

from rest_framework import exceptions

from .formatting import format_as_markdown
from .llm.gemini import SummarizationResult, summarize_with_gemini
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


class TestSummarizeWithGemini:
    """Error handling for edge cases and API failures."""

    def test_empty_responses_rejected_before_api_call(self):
        with pytest.raises(exceptions.ValidationError) as exc_info:
            summarize_with_gemini("Question", [])
        assert "responses cannot be empty" in str(exc_info.value.detail)

    @patch("products.surveys.backend.summarization.llm.gemini._get_client")
    def test_empty_api_response_raises_error(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.models.generate_content.return_value = MagicMock(text="")

        with pytest.raises(exceptions.ValidationError) as exc_info:
            summarize_with_gemini("Question", ["Response"])
        assert "empty response" in str(exc_info.value.detail)

    @patch("products.surveys.backend.summarization.llm.gemini._get_client")
    def test_api_error_wrapped_as_api_exception(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.models.generate_content.side_effect = Exception("API Error")

        with pytest.raises(exceptions.APIException) as exc_info:
            summarize_with_gemini("Question", ["Response"])
        assert "Failed to generate summary" in str(exc_info.value.detail)

    @patch("products.surveys.backend.summarization.llm.gemini._get_client")
    def test_returns_summarization_result_with_trace_id(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        valid_response = {
            "overview": "Users want better performance",
            "themes": [{"theme": "Speed", "description": "Fast loading times", "frequency": ">50%"}],
            "key_insight": "Focus on performance",
        }
        import json

        mock_client.models.generate_content.return_value = MagicMock(text=json.dumps(valid_response))

        result = summarize_with_gemini("What do you want?", ["Make it faster"])

        assert isinstance(result, SummarizationResult)
        assert isinstance(result.summary, SurveySummaryResponse)
        assert result.trace_id is not None
        assert len(result.trace_id) == 36  # UUID format
