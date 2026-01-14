class LLMError(Exception):
    """Base exception for LLM client errors"""


class UnsupportedModelError(LLMError):
    """Raised when an unsupported model is requested"""

    def __init__(self, model: str):
        self.model = model
        super().__init__(f"Unsupported model: {model}")


class UnsupportedProviderError(LLMError):
    """Raised when an unsupported provider is requested"""

    def __init__(self, provider: str):
        self.provider = provider
        super().__init__(f"Unsupported provider: {provider}")


class AuthenticationError(LLMError):
    """Raised when API key authentication fails"""


class RateLimitError(LLMError):
    """Raised when rate limit is exceeded"""


class QuotaExceededError(LLMError):
    """Raised when API quota is exceeded"""


class ProviderMismatchError(LLMError):
    """Raised when request provider doesn't match provider key's provider"""

    def __init__(self, key_provider: str, request_provider: str):
        self.key_provider = key_provider
        self.request_provider = request_provider
        super().__init__(f"Provider key is for '{key_provider}' but request specifies '{request_provider}'")
