from products.llm_analytics.backend.llm.providers.gemini import GeminiAdapter, GeminiConfig


class TestGeminiRecommendedModels:
    def test_recommended_models_equals_supported_models(self):
        assert GeminiAdapter.recommended_models() == set(GeminiConfig.SUPPORTED_MODELS)
