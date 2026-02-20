from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    api_key: str
    base_url: str | None = None


def get_eval_config(provider: str) -> ProviderConfig | None:
    """Get eval-specific provider config with fallback to general settings."""
    from django.conf import settings

    match provider:
        case "openai":
            api_key = settings.LLMA_EVAL_OPENAI_API_KEY or settings.OPENAI_API_KEY
            base_url = settings.LLMA_EVAL_OPENAI_BASE_URL or settings.OPENAI_BASE_URL
        case "anthropic":
            api_key = settings.LLMA_EVAL_ANTHROPIC_API_KEY or settings.ANTHROPIC_API_KEY
            base_url = None
        case "gemini":
            api_key = settings.LLMA_EVAL_GEMINI_API_KEY or settings.GEMINI_API_KEY
            base_url = None
        case _:
            return None

    if not api_key:
        return None
    return ProviderConfig(api_key=api_key, base_url=base_url)
