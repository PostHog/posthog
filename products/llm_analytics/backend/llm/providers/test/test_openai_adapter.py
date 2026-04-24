import pytest
from unittest.mock import MagicMock, patch

import httpx
import openai

from products.llm_analytics.backend.llm.errors import QuotaExceededError
from products.llm_analytics.backend.llm.providers.openai import OpenAIAdapter, OpenAIConfig
from products.llm_analytics.backend.llm.types import AnalyticsContext, CompletionRequest


class TestOpenAIRecommendedModels:
    def test_recommended_models_equals_supported_models(self):
        assert OpenAIAdapter.recommended_models() == set(OpenAIConfig.SUPPORTED_MODELS)


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
