"""Tests for survey summarization module."""

import json

import pytest
from unittest.mock import MagicMock, patch

from rest_framework import exceptions

from .formatting import format_as_markdown
from .llm.anthropic import SummarizationResult, summarize_with_anthropic
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


def _mock_gateway_client(content: str) -> MagicMock:
    """A build_openai_client stand-in whose chat completion returns `content`."""
    mock_client = MagicMock()
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=content))]
    mock_client.chat.completions.create.return_value = completion
    return mock_client


VALID_RESPONSE = json.dumps(
    {
        "overview": "Users want better performance",
        "themes": [{"theme": "Speed", "description": "Fast loading times", "frequency": ">50%"}],
        "key_insight": "Focus on performance",
    }
)


class TestSummarizeWithAnthropic:
    """Error handling and gateway tagging for the Anthropic-via-ai-gateway path."""

    def test_empty_responses_rejected_before_api_call(self):
        with pytest.raises(exceptions.ValidationError) as exc_info:
            summarize_with_anthropic("Question", [])
        assert "responses cannot be empty" in str(exc_info.value.detail)

    @patch("products.surveys.backend.summarization.llm.anthropic.build_openai_client")
    def test_empty_api_response_raises_error(self, mock_build_client):
        mock_build_client.return_value = _mock_gateway_client("")

        with pytest.raises(exceptions.ValidationError) as exc_info:
            summarize_with_anthropic("Question", ["Response"])
        assert "empty response" in str(exc_info.value.detail)

    @patch("products.surveys.backend.summarization.llm.anthropic.build_openai_client")
    def test_api_error_wrapped_as_api_exception(self, mock_build_client):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API Error")
        mock_build_client.return_value = mock_client

        with pytest.raises(exceptions.APIException) as exc_info:
            summarize_with_anthropic("Question", ["Response"])
        assert "Failed to generate response" in str(exc_info.value.detail)

    @patch("products.surveys.backend.summarization.llm.anthropic.build_openai_client")
    def test_returns_summarization_result_with_trace_id(self, mock_build_client):
        mock_build_client.return_value = _mock_gateway_client(VALID_RESPONSE)

        result = summarize_with_anthropic("What do you want?", ["Make it faster"])

        assert isinstance(result, SummarizationResult)
        assert isinstance(result.summary, SurveySummaryResponse)
        assert result.trace_id is not None
        assert len(result.trace_id) == 36  # UUID format

    @patch("products.surveys.backend.summarization.llm.anthropic.build_openai_client")
    def test_routes_to_gateway_with_product_and_cheap_model(self, mock_build_client):
        mock_client = _mock_gateway_client(VALID_RESPONSE)
        mock_build_client.return_value = mock_client

        summarize_with_anthropic("What do you want?", ["Make it faster"])

        create_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert mock_build_client.call_args.args[0] == "survey_summary"
        assert create_kwargs["model"] == "claude-haiku-4-5"
        assert create_kwargs["response_format"] == {"type": "json_object"}

    @patch("products.surveys.backend.summarization.llm.anthropic.build_openai_client")
    def test_stamps_gateway_properties_and_trace(self, mock_build_client):
        mock_client = _mock_gateway_client(VALID_RESPONSE)
        mock_build_client.return_value = mock_client

        result = summarize_with_anthropic(
            "What do you want?",
            ["Make it faster", "Add dark mode"],
            distinct_id="user-9",
            survey_id="s-1",
            question_id="q-1",
            team_id=42,
        )

        create_kwargs = mock_client.chat.completions.create.call_args.kwargs
        # distinct_id rides `user=` for per-user analytics/rate-limiting.
        assert create_kwargs["user"] == "user-9"
        headers = create_kwargs["extra_headers"]
        assert headers["X-PostHog-Trace-Id"] == result.trace_id
        properties = json.loads(headers["X-PostHog-Properties"])
        assert properties["ai_product"] == "survey_summary"
        assert properties["ai_feature"] == "survey_summary"
        # team_id keys per-team spend; dropping it collapses every team onto the bearer's team.
        assert properties["team_id"] == 42
        assert properties["survey_id"] == "s-1"
        assert properties["question_id"] == "q-1"
        assert properties["response_count"] == 2

    @patch("products.surveys.backend.summarization.llm.anthropic.build_openai_client")
    def test_omits_user_and_team_when_absent(self, mock_build_client):
        mock_client = _mock_gateway_client(VALID_RESPONSE)
        mock_build_client.return_value = mock_client

        summarize_with_anthropic("What do you want?", ["Make it faster"])

        create_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "user" not in create_kwargs
        assert "team_id" not in json.loads(create_kwargs["extra_headers"]["X-PostHog-Properties"])
