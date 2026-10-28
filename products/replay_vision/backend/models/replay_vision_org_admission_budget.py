from django.db import models


class ReplayVisionOrgAdmissionBudget(models.Model):
    """The scanner admission cache one level up, so the org credit limit holds under concurrent applies."""

    # No DB constraint: adding one locks posthog_organization, a hot table. Django still cascades the delete.
    organization = models.OneToOneField(
        "posthog.Organization",
        on_delete=models.CASCADE,
        primary_key=True,
        db_constraint=False,
        related_name="+",
    )
    period_start = models.DateTimeField(
        help_text="Billing period the cached budget belongs to. A period mismatch forces a refresh.",
    )
    credit_limit = models.PositiveIntegerField(
        null=True,
        help_text="Org credit limit at the last refresh, null when billing sets none. A fast-path admission requires the current limit to match it.",
    )
    credits_used = models.PositiveIntegerField(
        help_text="Credits counted against credit_limit at the last refresh: settled receipts plus in-flight reservations.",
    )
    credits_since_refresh = models.PositiveIntegerField(
        default=0,
        help_text="Credits admitted since the last refresh. Every refresh resets it to the admitting cost, or zero on refusal.",
    )
    refreshed_at = models.DateTimeField(
        help_text="When the spend aggregates were last recomputed.",
    )
