import pytest
from unittest.mock import AsyncMock, patch

from products.llm_analytics.backend.summarization.constants import (
    DEFAULT_MODE,
    DEFAULT_MODEL_GEMINI,
    DEFAULT_MODEL_OPENAI,
    DEFAULT_PROVIDER,
)
from products.llm_analytics.backend.summarization.llm.call import summarize
from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse
from products.llm_analytics.backend.summarization.models import (
    GeminiModel,
    OpenAIModel,
    SummarizationMode,
    SummarizationProvider,
)


@pytest.fixture
def mock_response():
    return SummarizationResponse(
        title="Test Summary",
        flow_diagram="User → Assistant",
        summary_bullets=[{"text": "Test bullet", "line_refs": "L1"}],
        interesting_notes=[],
    )


class TestSummarize:
    @pytest.mark.asyncio
    async def test_default_provider_is_openai(self):
        assert DEFAULT_PROVIDER == SummarizationProvider.OPENAI

    @pytest.mark.asyncio
    async def test_uses_openai_by_default(self, mock_response):
        with patch(
            "products.llm_analytics.backend.summarization.llm.call.summarize_with_openai",
            new_callable=AsyncMock,
        ) as mock_openai:
            mock_openai.return_value = mock_response

            result = await summarize(
                text_repr="L1: Test content",
                team_id=1,
            )

            mock_openai.assert_called_once_with(
                "L1: Test content",
                1,
                DEFAULT_MODE,
                DEFAULT_MODEL_OPENAI,
            )
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_uses_gemini_when_specified(self, mock_response):
        with patch(
            "products.llm_analytics.backend.summarization.llm.call.summarize_with_gemini",
            new_callable=AsyncMock,
        ) as mock_gemini:
            mock_gemini.return_value = mock_response

            result = await summarize(
                text_repr="L1: Test content",
                team_id=1,
                provider=SummarizationProvider.GEMINI,
            )

            mock_gemini.assert_called_once_with(
                "L1: Test content",
                1,
                DEFAULT_MODE,
                DEFAULT_MODEL_GEMINI,
            )
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_openai_uses_custom_model(self, mock_response):
        with patch(
            "products.llm_analytics.backend.summarization.llm.call.summarize_with_openai",
            new_callable=AsyncMock,
        ) as mock_openai:
            mock_openai.return_value = mock_response

            await summarize(
                text_repr="L1: Test",
                team_id=1,
                provider=SummarizationProvider.OPENAI,
                model=OpenAIModel.GPT_4O,
            )

            mock_openai.assert_called_once()
            call_args = mock_openai.call_args[0]
            assert call_args[3] == OpenAIModel.GPT_4O

    @pytest.mark.asyncio
    async def test_gemini_uses_custom_model(self, mock_response):
        with patch(
            "products.llm_analytics.backend.summarization.llm.call.summarize_with_gemini",
            new_callable=AsyncMock,
        ) as mock_gemini:
            mock_gemini.return_value = mock_response

            await summarize(
                text_repr="L1: Test",
                team_id=1,
                provider=SummarizationProvider.GEMINI,
                model=GeminiModel.GEMINI_2_0_FLASH,
            )

            mock_gemini.assert_called_once()
            call_args = mock_gemini.call_args[0]
            assert call_args[3] == GeminiModel.GEMINI_2_0_FLASH

    @pytest.mark.asyncio
    async def test_mode_is_passed_through(self, mock_response):
        with patch(
            "products.llm_analytics.backend.summarization.llm.call.summarize_with_openai",
            new_callable=AsyncMock,
        ) as mock_openai:
            mock_openai.return_value = mock_response

            await summarize(
                text_repr="L1: Test",
                team_id=1,
                mode=SummarizationMode.DETAILED,
            )

            call_args = mock_openai.call_args[0]
            assert call_args[2] == SummarizationMode.DETAILED

    @pytest.mark.asyncio
    async def test_team_id_is_passed_through(self, mock_response):
        with patch(
            "products.llm_analytics.backend.summarization.llm.call.summarize_with_openai",
            new_callable=AsyncMock,
        ) as mock_openai:
            mock_openai.return_value = mock_response

            await summarize(
                text_repr="L1: Test",
                team_id=42,
            )

            call_args = mock_openai.call_args[0]
            assert call_args[1] == 42

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "provider,expected_default_model",
        [
            (SummarizationProvider.OPENAI, DEFAULT_MODEL_OPENAI),
            (SummarizationProvider.GEMINI, DEFAULT_MODEL_GEMINI),
        ],
    )
    async def test_default_models_per_provider(self, mock_response, provider, expected_default_model):
        patch_target = (
            "products.llm_analytics.backend.summarization.llm.call.summarize_with_gemini"
            if provider == SummarizationProvider.GEMINI
            else "products.llm_analytics.backend.summarization.llm.call.summarize_with_openai"
        )

        with patch(patch_target, new_callable=AsyncMock) as mock_provider:
            mock_provider.return_value = mock_response

            await summarize(
                text_repr="L1: Test",
                team_id=1,
                provider=provider,
            )

            call_args = mock_provider.call_args[0]
            assert call_args[3] == expected_default_model
