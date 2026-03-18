from django.test import SimpleTestCase

from parameterized import parameterized

from products.llm_analytics.backend.llm.errors import (
    AuthenticationError,
    LLMError,
    ModelNotFoundError,
    ModelPermissionError,
    ProviderMismatchError,
    QuotaExceededError,
    RateLimitError,
    UnsupportedModelError,
    UnsupportedProviderError,
)


class TestLLMErrors(SimpleTestCase):
    def test_llm_error_is_exception(self):
        error = LLMError("test error")
        assert isinstance(error, Exception)
        assert str(error) == "test error"

    def test_unsupported_model_error(self):
        error = UnsupportedModelError("gpt-99")
        assert error.model == "gpt-99"
        assert "gpt-99" in str(error)
        assert isinstance(error, LLMError)

    def test_unsupported_provider_error(self):
        error = UnsupportedProviderError("unknown_provider")
        assert error.provider == "unknown_provider"
        assert "unknown_provider" in str(error)
        assert isinstance(error, LLMError)

    def test_authentication_error(self):
        error = AuthenticationError("Invalid API key")
        assert "Invalid API key" in str(error)
        assert isinstance(error, LLMError)

    def test_rate_limit_error(self):
        error = RateLimitError("Too many requests")
        assert isinstance(error, LLMError)

    def test_quota_exceeded_error(self):
        error = QuotaExceededError("Quota exceeded")
        assert isinstance(error, LLMError)

    def test_provider_mismatch_error(self):
        error = ProviderMismatchError("openai", "anthropic")
        assert error.key_provider == "openai"
        assert error.request_provider == "anthropic"
        assert "openai" in str(error)
        assert "anthropic" in str(error)
        assert isinstance(error, LLMError)

    def test_model_not_found_error(self):
        error = ModelNotFoundError("gpt-99")
        assert error.model == "gpt-99"
        assert "gpt-99" in str(error)
        assert "not found" in str(error).lower()
        assert isinstance(error, LLMError)

    def test_model_permission_error_with_model(self):
        error = ModelPermissionError("gpt-4o")
        assert error.model == "gpt-4o"
        assert "gpt-4o" in str(error)
        assert "access" in str(error).lower()
        assert isinstance(error, LLMError)

    def test_model_permission_error_without_model(self):
        error = ModelPermissionError()
        assert error.model is None
        assert "access" in str(error).lower()
        assert isinstance(error, LLMError)


class TestErrorHierarchy(SimpleTestCase):
    @parameterized.expand(
        [
            (UnsupportedModelError("test"),),
            (UnsupportedProviderError("test"),),
            (AuthenticationError("test"),),
            (RateLimitError("test"),),
            (QuotaExceededError("test"),),
            (ProviderMismatchError("a", "b"),),
            (ModelNotFoundError("test"),),
            (ModelPermissionError("test"),),
        ]
    )
    def test_all_errors_inherit_from_llm_error(self, error):
        assert isinstance(error, LLMError)
        assert isinstance(error, Exception)

    @parameterized.expand(
        [
            (UnsupportedModelError("test"),),
            (UnsupportedProviderError("test"),),
            (AuthenticationError("test"),),
            (RateLimitError("test"),),
            (QuotaExceededError("test"),),
            (ProviderMismatchError("a", "b"),),
            (ModelNotFoundError("test"),),
            (ModelPermissionError("test"),),
        ]
    )
    def test_errors_can_be_caught_as_llm_error(self, error):
        caught = False
        try:
            raise error
        except LLMError:
            caught = True
        assert caught
