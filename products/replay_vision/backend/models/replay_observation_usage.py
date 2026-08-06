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
    team_id = models.BigIntegerField(
        null=True,
        help_text="The observation's team; the per-team billing usage report groups on this (plain id, no FK).",
    )
    observation_created_at = models.DateTimeField(
        help_text="The observation's created_at; the monthly quota window filters on this.",
    )
    model = models.CharField(
        max_length=64,
        null=True,
        help_text="Model id frozen from the observation's scanner_snapshot; kept for audit and re-pricing analysis.",
    )
    credits = models.PositiveIntegerField(
        null=True,
        help_text="Credits billed for this observation (1 credit = $0.01), frozen at success time so price changes never reprice history.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "observation_created_at"]),
            # Drives the daily per-team billing usage query, which buckets receipts by write time.
            models.Index(fields=["created_at", "team_id"], name="rlou_created_team_idx"),
        ]

    def __str__(self) -> str:
        return f"usage {self.observation_id} ({self.organization_id})"
