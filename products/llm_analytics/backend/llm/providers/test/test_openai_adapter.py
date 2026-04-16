from unittest.mock import MagicMock

from parameterized import parameterized
from posthoganalytics.ai.openai import (
    AzureOpenAI as WrappedAzureOpenAI,
    OpenAI as WrappedOpenAI,
)

from products.llm_analytics.backend.llm.providers.openai import OpenAIAdapter, OpenAIConfig
from products.llm_analytics.backend.llm.types import AnalyticsContext


class TestOpenAIRecommendedModels:
    def test_recommended_models_equals_supported_models(self):
        assert OpenAIAdapter.recommended_models() == set(OpenAIConfig.SUPPORTED_MODELS)


class TestBuildAnalyticsKwargs:
    @parameterized.expand(
        [
            ("wrapped_openai", WrappedOpenAI),
            ("wrapped_azure_openai", WrappedAzureOpenAI),
        ]
    )
    def test_wrapped_clients_get_analytics_kwargs_when_capture_enabled(self, _name, client_cls):
        adapter = OpenAIAdapter()
        client = MagicMock(spec=client_cls)
        analytics = AnalyticsContext(distinct_id="user-1", trace_id="trace-1", capture=True)

        kwargs = adapter._build_analytics_kwargs(analytics, client)

        assert kwargs == {
            "posthog_distinct_id": "user-1",
            "posthog_trace_id": "trace-1",
            "posthog_properties": {},
            "posthog_groups": {},
        }

    def test_capture_disabled_returns_empty_kwargs(self):
        adapter = OpenAIAdapter()
        client = MagicMock(spec=WrappedOpenAI)
        analytics = AnalyticsContext(distinct_id="user-1", trace_id="trace-1", capture=False)

        kwargs = adapter._build_analytics_kwargs(analytics, client)

        assert kwargs == {}

    def test_unknown_client_returns_empty_kwargs(self):
        """A non-wrapped client (e.g. raw openai.OpenAI) should not receive analytics kwargs."""
        adapter = OpenAIAdapter()
        client = MagicMock()  # no spec — not an instance of Wrapped*
        analytics = AnalyticsContext(distinct_id="user-1", trace_id="trace-1", capture=True)

        kwargs = adapter._build_analytics_kwargs(analytics, client)

        assert kwargs == {}
