import uuid

from django.db import models
from django.utils import timezone

from posthog.models.scoping.product_mixin import ProductTeamModel


class Monitor(ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    url = models.URLField(max_length=2048)
    created_at = models.DateTimeField(auto_now_add=True)
    # How often this monitor should be pinged. The rust pinger advances next_check_at by this
    # value after each claim. Hardcoded to 5 minutes for v1 — the column exists so we can expose
    # per-monitor cadence in the UI later without another migration.
    interval_seconds = models.PositiveIntegerField(default=300)
    # When the rust pinger next becomes eligible to claim this monitor. Indexed because the claim
    # query is `WHERE next_check_at <= now() ... FOR UPDATE SKIP LOCKED`.
    next_check_at = models.DateTimeField(default=timezone.now, db_index=True)
    # Workers stamp this when claiming. The claim query only ignores it implicitly — next_check_at
    # is what gates re-pick. We keep the column so a future janitor or dashboard can show stuck claims.
    leased_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name
