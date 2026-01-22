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


class ModelNotFoundError(LLMError):
    """Raised when a requested model is not found"""

    def __init__(self, model: str):
        self.model = model
        super().__init__(f"Model '{model}' not found")


class ModelPermissionError(LLMError):
    """Raised when the API key doesn't have permission to access a model"""

    def __init__(self, model: str | None = None):
        self.model = model
        msg = (
            f"API key doesn't have access to model '{model}'" if model else "API key doesn't have access to this model"
        )
        super().__init__(msg)
