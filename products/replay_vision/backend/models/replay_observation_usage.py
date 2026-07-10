from django.db import models

from posthog.models.utils import UUIDModel


class ReplayObservationUsage(UUIDModel):
    """Immutable usage receipt, decoupled from the observation row so deletes can't refund spent quota.

    Observations write their own id on success. Prompt-suggestion test runs write a synthetic
    per-session id (`prompt_evaluation.evaluation_usage_id`).
    """

    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="replay_observation_usage",
    )
    observation_id = models.UUIDField(
        unique=True,
        help_text="The observation this receipt accounts for (plain id, no FK).",
    )
    observation_created_at = models.DateTimeField(
        help_text="The observation's created_at; the monthly quota window filters on this.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "observation_created_at"]),
        ]

    def __str__(self) -> str:
        return f"usage {self.observation_id} ({self.organization_id})"
