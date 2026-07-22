from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from posthog.models.utils import UUIDModel

# Generous upper bound — catches admin typos (5000 vs 5000000) without rejecting any plausible grant.
MAX_GRANT_AMOUNT = 1_000_000


class ReplayQuotaGrant(UUIDModel):
    """Bonus credit budget for an organization, valid until `expires_at`.

    Active grants are summed into the organization's effective credit limit; see
    `products.replay_vision.backend.quota.compute_quota_snapshot`. At and after `expires_at`, grants stop counting.
    """

    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="replay_quota_grants",
    )
    amount = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(MAX_GRANT_AMOUNT)],
        help_text=f"Extra credits granted on top of the base monthly credit limit (1–{MAX_GRANT_AMOUNT:,}).",
    )
    expires_at = models.DateTimeField(
        help_text="Grant is valid up to but not including this timestamp. Defaults to the start of next month.",
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    granted_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Staff user who granted this bonus.",
    )
    reason = models.TextField(
        blank=True,
        default="",
        help_text="Free-form note explaining why the bonus was granted.",
    )

    class Meta:
        ordering = ["-granted_at"]
        indexes = [
            # Active-grant lookup: filter by organization, then by `expires_at > now`.
            models.Index(fields=["organization", "expires_at"]),
        ]

    def __str__(self) -> str:
        return f"+{self.amount} for {self.organization_id}"

    def clean(self) -> None:
        super().clean()
        if self.expires_at and self.expires_at <= timezone.now():
            raise ValidationError({"expires_at": "Expiry must be in the future."})
