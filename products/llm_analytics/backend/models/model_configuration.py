from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.utils import UUIDTModel

from .provider_keys import LLMProvider

# Cost-controlled models for PostHog default keys
POSTHOG_ALLOWED_MODELS: dict[str, list[str]] = {
    "openai": ["gpt-5-mini"],
    "anthropic": ["claude-3-5-haiku-20241022"],
    "gemini": ["gemini-2.0-flash-lite"],
}


class LLMModelConfiguration(UUIDTModel):
    """Configuration for LLM model selection, used by evals and other features."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    provider = models.CharField(max_length=50, choices=LLMProvider.choices)
    model = models.CharField(max_length=100)
    provider_key = models.ForeignKey(
        "llm_analytics.LLMProviderKey",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="model_configurations",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "llm_analytics"
        indexes = [
            models.Index(fields=["team", "provider"]),
        ]

    def __str__(self) -> str:
        key_info = f" (key: {self.provider_key.name})" if self.provider_key else " (PostHog default)"
        return f"{self.provider}/{self.model}{key_info}"

    def clean(self) -> None:
        """Django validation - works for both persisted and in-memory instances."""
        super().clean()
        self._validate_provider_key_match()

    def _validate_provider_key_match(self) -> None:
        """If a key is set, provider must match the key's provider."""
        if self.provider_key and self.provider_key.provider != self.provider:
            raise ValidationError(
                {"provider": f"Provider '{self.provider}' does not match key provider '{self.provider_key.provider}'"}
            )

    def get_available_models(self) -> list[str]:
        """Get available models - delegates to API if key present, otherwise returns PostHog allowed list."""
        if self.provider_key:
            from products.llm_analytics.backend.llm.client import Client

            api_key = self.provider_key.encrypted_config.get("api_key")
            return Client.list_models(self.provider, api_key)
        return POSTHOG_ALLOWED_MODELS.get(self.provider, [])

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
