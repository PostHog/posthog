from django.db import models

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.utils import UUIDTModel


class LLMProvider(models.TextChoices):
    """Shared provider enum for all LLM-related models."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"


class LLMProviderKey(UUIDTModel):
    class State(models.TextChoices):
        UNKNOWN = "unknown"
        OK = "ok"
        INVALID = "invalid"
        ERROR = "error"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    provider = models.CharField(max_length=50, choices=LLMProvider.choices)
    name = models.CharField(max_length=255)
    state = models.CharField(max_length=20, choices=State.choices, default=State.UNKNOWN)
    error_message = models.TextField(null=True, blank=True)
    encrypted_config = EncryptedJSONField(default=dict, ignore_decrypt_errors=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "provider"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.provider})"
