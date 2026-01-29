import pytest
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from parameterized import parameterized

from products.llm_analytics.backend.llm.client import Client
from products.llm_analytics.backend.llm.errors import ProviderMismatchError, UnsupportedProviderError
from products.llm_analytics.backend.llm.types import CompletionRequest


class TestClientInitialization(SimpleTestCase):
    def test_default_initialization(self):
        client = Client()
        assert client.provider_key is None
        assert client.analytics.distinct_id == ""
        assert client.analytics.capture is True
        assert client.analytics.trace_id is not None

    def test_initialization_with_kwargs(self):
        client = Client(
            distinct_id="test-user",
            trace_id="test-trace-id",
            capture_analytics=False,
        )
        assert client.analytics.distinct_id == "test-user"
        assert client.analytics.trace_id == "test-trace-id"
        assert client.analytics.capture is False

    def test_trace_id_generated_when_not_provided(self):
        client = Client(distinct_id="test")
        assert client.analytics.trace_id is not None
        assert len(client.analytics.trace_id) == 36


class TestProviderRouting(SimpleTestCase):
    @parameterized.expand(
        [
            ("openai",),
            ("anthropic",),
            ("gemini",),
        ]
    )
    def test_get_provider_returns_correct_adapter(self, provider_name):
        from products.llm_analytics.backend.llm.client import _get_provider

        provider = _get_provider(provider_name)
        assert provider.name == provider_name

    def test_get_provider_raises_for_unsupported(self):
        from products.llm_analytics.backend.llm.client import _get_provider

        with pytest.raises(UnsupportedProviderError) as exc:
            _get_provider("unsupported")
        assert "unsupported" in str(exc.value)


class TestProviderMismatchValidation(SimpleTestCase):
    def test_provider_mismatch_raises_error(self):
        mock_key = MagicMock()
        mock_key.provider = "openai"
        mock_key.encrypted_config = {"api_key": "test-key"}

        client = Client(provider_key=mock_key)

        request = CompletionRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[{"role": "user", "content": "hi"}],
            provider="anthropic",
        )

        with pytest.raises(ProviderMismatchError) as exc:
            client.complete(request)
        assert "openai" in str(exc.value)
        assert "anthropic" in str(exc.value)

    def test_matching_provider_does_not_raise(self):
        mock_key = MagicMock()
        mock_key.provider = "openai"
        mock_key.encrypted_config = {"api_key": "test-key"}

        client = Client(provider_key=mock_key)

        client._validate_provider("openai")

    def test_no_provider_key_allows_any_provider(self):
        client = Client()
        client._validate_provider("openai")
        client._validate_provider("anthropic")
        client._validate_provider("gemini")


class TestApiKeyExtraction(SimpleTestCase):
    def test_get_api_key_with_provider_key(self):
        mock_key = MagicMock()
        mock_key.encrypted_config = {"api_key": "secret-key"}

        client = Client(provider_key=mock_key)

        assert client._get_api_key() == "secret-key"

    def test_get_api_key_without_provider_key(self):
        client = Client()
        assert client._get_api_key() is None
