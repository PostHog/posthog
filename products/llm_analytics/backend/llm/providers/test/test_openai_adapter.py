import pytest
from unittest.mock import MagicMock, patch

import httpx
import openai
from parameterized import parameterized
from posthoganalytics.ai.openai import (
    AzureOpenAI as WrappedAzureOpenAI,
    OpenAI as WrappedOpenAI,
)

from products.llm_analytics.backend.llm.errors import QuotaExceededError
from products.llm_analytics.backend.llm.providers.openai import OpenAIAdapter, OpenAIConfig
from products.llm_analytics.backend.llm.types import AnalyticsContext, CompletionRequest


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


def _make_api_status_error(status_code: int, message: str) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    response = httpx.Response(status_code=status_code, request=request, json={"error": {"message": message}})
    return openai.APIStatusError(message, response=response, body={"error": {"message": message, "code": status_code}})


class TestOpenAIAdapterErrorMapping:
    @pytest.fixture
    def request_no_structured_output(self) -> CompletionRequest:
        return CompletionRequest(
            model="gpt-4.1",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            provider="openai",
        )

    def test_402_is_mapped_to_quota_exceeded(self, request_no_structured_output: CompletionRequest):
        adapter = OpenAIAdapter()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = _make_api_status_error(
            402, "This request requires more credits, or fewer max_tokens."
        )

        with patch("products.llm_analytics.backend.llm.providers.openai.openai.OpenAI", return_value=mock_client):
            with pytest.raises(QuotaExceededError, match="credits"):
                adapter.complete(
                    request_no_structured_output, api_key="sk-test", analytics=AnalyticsContext(capture=False)
                )

    def test_non_402_status_error_is_not_swallowed(self, request_no_structured_output: CompletionRequest):
        adapter = OpenAIAdapter()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = _make_api_status_error(500, "server error")

        with patch("products.llm_analytics.backend.llm.providers.openai.openai.OpenAI", return_value=mock_client):
            with pytest.raises(openai.APIStatusError):
                adapter.complete(
                    request_no_structured_output, api_key="sk-test", analytics=AnalyticsContext(capture=False)
                )
