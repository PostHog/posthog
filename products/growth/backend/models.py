from django.db import models
from django.db.models import Q

from posthog.models.utils import UpdatedMetaFields, UUIDModel


class ProductPushCampaign(UUIDModel, UpdatedMetaFields):
    """One product pushed to a whole organization for a bounded window.

    A single table holds the queue (SCHEDULED), the current push (ACTIVE), and the
    history (ADOPTED / SKIPPED / CANCELLED) — promoting a scheduled row to active is
    a status flip, not a row move. Cadence, selection, and transitions live in
    products/growth/backend/product_push/.
    """

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        ACTIVE = "active", "Active"
        ADOPTED = "adopted", "Adopted"
        SKIPPED = "skipped", "Skipped"
        CANCELLED = "cancelled", "Cancelled"

    class Source(models.TextChoices):
        AUTO = "auto", "Auto"
        TAM = "tam", "TAM"

    # No DB constraints on the FKs: posthog_organization and posthog_user are hot
    # tables, and building an FK constraint takes a lock on the referenced parent
    # (see safe-django-migrations.md "Foreign keys to hot tables").
    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="product_push_campaigns",
        db_constraint=False,
    )
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
    )

    # A ProductKey value. Plain CharField (like ProductIntent.product_type) so the
    # enum can grow without a migration; the admin form constrains input at runtime.
    product_key = models.CharField(max_length=255)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SCHEDULED)

    # Ordering among an org's SCHEDULED rows; lower starts sooner.
    position = models.PositiveIntegerField(default=0)

    scheduled_for = models.DateField(
        null=True,
        blank=True,
        help_text="Don't start before this date. Overrides the signup grace period and the between-campaigns "
        "cooldown (an explicit human decision), but never the one-active-campaign-per-org invariant. "
        "Empty = next available slot.",
    )

    started_at = models.DateTimeField(null=True, blank=True)
    # Planned end (started_at + CAMPAIGN_DURATION_DAYS), denormalized so the daily
    # sweep can find expired campaigns with an index scan.
    ends_at = models.DateTimeField(null=True, blank=True)
    # Actual close time (adoption detected, expired, or cancelled).
    ended_at = models.DateTimeField(null=True, blank=True)

    source = models.CharField(max_length=8, choices=Source.choices, default=Source.AUTO)

    reason_text = models.TextField(
        null=True,
        blank=True,
        help_text="Custom copy for the in-app promo card. Empty = default copy.",
    )

    # Outcome details, e.g. {"adoption_signal": "intent_activated", "team_id": 123}.
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Product push campaign"
        verbose_name_plural = "Product push campaigns"
        constraints = [
            models.UniqueConstraint(
                fields=["organization"],
                condition=Q(status="active"),
                name="uniq_active_product_push_per_org",
            ),
            models.UniqueConstraint(
                fields=["organization", "product_key"],
                condition=Q(status__in=["scheduled", "active"]),
                name="uniq_pending_product_push_per_org_product",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status"], name="growth_push_org_status"),
            models.Index(fields=["status", "ends_at"], name="growth_push_status_ends_at"),
            models.Index(fields=["status", "scheduled_for"], name="growth_push_status_sched"),
        ]

    def __str__(self) -> str:
        return f"{self.organization_id} - {self.product_key} ({self.status})"
