import pytest
from unittest.mock import patch

from products.llm_analytics.backend.summarization.constants import DEFAULT_MODE, DEFAULT_MODEL_OPENAI
from products.llm_analytics.backend.summarization.llm.call import summarize
from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse
from products.llm_analytics.backend.summarization.models import OpenAIModel, SummarizationMode


@pytest.fixture
def mock_response():
    return SummarizationResponse(
        title="Test Summary",
        flow_diagram="User -> Assistant",
        summary_bullets=[{"text": "Test bullet", "line_refs": "L1"}],
        interesting_notes=[],
    )


class TestSummarize:
    def test_uses_openai_by_default(self, mock_response):
        with patch(
            "products.llm_analytics.backend.summarization.llm.call.summarize_with_openai",
        ) as mock_openai:
            mock_openai.return_value = mock_response

            result = summarize(
                text_repr="L1: Test content",
                team_id=1,
            )

            mock_openai.assert_called_once_with(
                "L1: Test content",
                1,
                DEFAULT_MODE,
                DEFAULT_MODEL_OPENAI,
                None,
            )
            assert result == mock_response

    def test_uses_custom_model(self, mock_response):
        with patch(
            "products.llm_analytics.backend.summarization.llm.call.summarize_with_openai",
        ) as mock_openai:
            mock_openai.return_value = mock_response

            summarize(
                text_repr="L1: Test",
                team_id=1,
                model=OpenAIModel.GPT_4_1_MINI,
            )

            mock_openai.assert_called_once()
            call_args = mock_openai.call_args[0]
            assert call_args[3] == OpenAIModel.GPT_4_1_MINI

    def test_mode_is_passed_through(self, mock_response):
        with patch(
            "products.llm_analytics.backend.summarization.llm.call.summarize_with_openai",
        ) as mock_openai:
            mock_openai.return_value = mock_response

            summarize(
                text_repr="L1: Test",
                team_id=1,
                mode=SummarizationMode.DETAILED,
            )

            call_args = mock_openai.call_args[0]
            assert call_args[2] == SummarizationMode.DETAILED

    def test_team_id_is_passed_through(self, mock_response):
        with patch(
            "products.llm_analytics.backend.summarization.llm.call.summarize_with_openai",
        ) as mock_openai:
            mock_openai.return_value = mock_response

            summarize(
                text_repr="L1: Test",
                team_id=42,
            )

            call_args = mock_openai.call_args[0]
            assert call_args[1] == 42

    def test_user_id_is_passed_through(self, mock_response):
        with patch(
            "products.llm_analytics.backend.summarization.llm.call.summarize_with_openai",
        ) as mock_openai:
            mock_openai.return_value = mock_response

            summarize(
                text_repr="L1: Test",
                team_id=1,
                user_id="user-123",
            )

            call_args = mock_openai.call_args[0]
            assert call_args[4] == "user-123"
