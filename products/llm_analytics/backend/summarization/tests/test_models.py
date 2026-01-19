import pytest

from products.llm_analytics.backend.summarization.models import (
    GeminiModel,
    OpenAIModel,
    SummarizationMode,
    SummarizationProvider,
)


class TestSummarizationProvider:
    @pytest.mark.parametrize(
        "provider,expected_value",
        [
            (SummarizationProvider.OPENAI, "openai"),
            (SummarizationProvider.GEMINI, "gemini"),
        ],
    )
    def test_provider_values(self, provider, expected_value):
        assert provider.value == expected_value
        assert str(provider) == expected_value

    def test_provider_from_string(self):
        assert SummarizationProvider("openai") == SummarizationProvider.OPENAI
        assert SummarizationProvider("gemini") == SummarizationProvider.GEMINI

    def test_provider_invalid_value_raises(self):
        with pytest.raises(ValueError):
            SummarizationProvider("invalid")


class TestOpenAIModel:
    @pytest.mark.parametrize(
        "model,expected_value",
        [
            (OpenAIModel.GPT_4_1_MINI, "gpt-4.1-mini"),
            (OpenAIModel.GPT_4O_MINI, "gpt-4o-mini"),
            (OpenAIModel.GPT_4O, "gpt-4o"),
        ],
    )
    def test_model_values(self, model, expected_value):
        assert model.value == expected_value
        assert str(model) == expected_value


class TestGeminiModel:
    @pytest.mark.parametrize(
        "model,expected_value",
        [
            (GeminiModel.GEMINI_3_FLASH_PREVIEW, "gemini-3-flash-preview"),
            (GeminiModel.GEMINI_2_5_FLASH, "gemini-2.5-flash"),
            (GeminiModel.GEMINI_2_0_FLASH, "gemini-2.0-flash"),
        ],
    )
    def test_model_values(self, model, expected_value):
        assert model.value == expected_value
        assert str(model) == expected_value


class TestSummarizationMode:
    @pytest.mark.parametrize(
        "mode,expected_value",
        [
            (SummarizationMode.MINIMAL, "minimal"),
            (SummarizationMode.DETAILED, "detailed"),
        ],
    )
    def test_mode_values(self, mode, expected_value):
        assert mode.value == expected_value
        assert str(mode) == expected_value

    def test_mode_from_string(self):
        assert SummarizationMode("minimal") == SummarizationMode.MINIMAL
        assert SummarizationMode("detailed") == SummarizationMode.DETAILED
