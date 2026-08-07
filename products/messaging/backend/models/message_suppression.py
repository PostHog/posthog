from django.db import models
from django.db.models import Q

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class SuppressionSource(models.TextChoices):
    # Added automatically after an address repeatedly soft-bounced (see the transient
    # bounce handling in the SES webhook path).
    BOUNCE = "BOUNCE"
    # Added by a user via the Suppression list tab / API.
    MANUAL = "MANUAL"


class MessageSuppression(TeamScopedRootMixin, UUIDModel):
    """
    Per-team list of email addresses we should not send to because they can't (or shouldn't)
    receive mail. Two ways an address lands here:

    - Automatically, when it soft-bounces (`Transient`) on `transient_bounce_count` consecutive
      sends without a successful delivery in between. A single soft bounce is not enough — the
      recipient server may just be briefly down — so we count and only suppress once the count
      crosses a configurable threshold. Any successful delivery resets the count.
    - Manually, when a user adds it in the Suppression list UI.

    The pre-send path consults this list (see the Node `EmailSuppressionService`) and skips
    matching recipients. Unlike opt-outs, a suppression is a deliverability signal, not a
    messaging preference, so it applies regardless of message category (including transactional).
    """

    # db_constraint=False on these hot-table FKs so CreateModel takes no lock on
    # posthog_team / posthog_user (see HotTableAlterPolicy / safe-django-migrations).
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    deleted = models.BooleanField(default=False)

    # Lower-cased recipient email address.
    identifier = models.CharField(max_length=512)

    source = models.CharField(max_length=16, choices=SuppressionSource.choices, default=SuppressionSource.BOUNCE)
    reason = models.TextField(null=True, blank=True)

    # Rolling count of consecutive soft bounces with no successful delivery in between.
    # Reset to 0 whenever the address successfully delivers. Ignored for manual entries.
    transient_bounce_count = models.IntegerField(default=0)
    last_bounce_at = models.DateTimeField(null=True, blank=True)
    # Last SMTP diagnostic we saw, kept for visibility in the UI (e.g. the "Message expired" text).
    last_bounce_diagnostic = models.TextField(null=True, blank=True)

    # Whether the address is actively suppressed. A row can exist while still only counting
    # bounces (suppressed=False) before it crosses the threshold.
    suppressed = models.BooleanField(default=False)
    suppressed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = (
            "team",
            "identifier",
        )
        db_table = "posthog_messagesuppression"
        indexes = [
            # Partial index for the Suppression list UI query:
            # WHERE team_id = ? AND suppressed = true AND deleted = false ORDER BY updated_at DESC
            # Small (only actively-suppressed rows) and sorted the way we read, so it also serves
            # the paginator COUNT without a full team scan.
            models.Index(
                fields=["team", "-updated_at"],
                name="pmsg_supp_active_by_updated",
                condition=Q(suppressed=True, deleted=False),
            ),
        ]

    def __str__(self) -> str:
        return f"Suppression for {self.identifier}"
