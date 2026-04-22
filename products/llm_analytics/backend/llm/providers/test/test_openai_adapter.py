from products.llm_analytics.backend.llm.providers.openai import OpenAIAdapter, OpenAIConfig


class TestOpenAIRecommendedModels:
    def test_recommended_models_equals_supported_models(self):
        assert OpenAIAdapter.recommended_models() == set(OpenAIConfig.SUPPORTED_MODELS)
