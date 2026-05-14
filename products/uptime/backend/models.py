import uuid

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

from posthog.models.scoping.product_mixin import ProductTeamModel


class Monitor(ProductTeamModel):
    class Mode(models.TextChoices):
        # PostHog pings the URL on a recurring schedule (~every 5 minutes) and computes
        # uptime / latency from the recorded ping outcomes. This is the default.
        AUTO = "auto", "Auto"
        # No background pinging. The monitor is assumed 100% up unless the user declares
        # an incident on it. Uptime % and daily buckets are computed from incident
        # windows; latency is null. URL is optional in this mode — useful for tracking
        # internal services or third-party dependencies without a public health endpoint.
        MANUAL = "manual", "Manual"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    # URL is nullable to support mode=manual monitors that track a service without a
    # pingable endpoint. For mode=auto we enforce non-null at the serializer layer.
    url = models.URLField(max_length=2048, null=True, blank=True)
    mode = models.CharField(max_length=16, choices=Mode.choices, default=Mode.AUTO)
    created_at = models.DateTimeField(auto_now_add=True)
    # User-controlled display order in the list view. Backfilled per-team from
    # creation order; smaller values render first.
    display_order = models.BigIntegerField(default=0, db_index=True)
    # How often this monitor should be pinged. The rust pinger advances next_check_at by this
    # value after each claim. Hardcoded to 60s for v1 — the column exists so we can expose
    # per-monitor cadence in the UI later without another migration.
    interval_seconds = models.PositiveIntegerField(default=60)
    # When the rust pinger next becomes eligible to claim this monitor. Indexed because the claim
    # query is `WHERE next_check_at <= now() ... FOR UPDATE SKIP LOCKED`.
    next_check_at = models.DateTimeField(default=timezone.now, db_index=True)
    # Workers stamp this when claiming. The claim query only ignores it implicitly — next_check_at
    # is what gates re-pick. We keep the column so a future janitor or dashboard can show stuck claims.
    leased_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        # ordering propagates to default querysets — newest-on-top tie-breaks
        # ties in display_order (e.g. all-zero for a team that's never reordered).
        ordering = ["display_order", "-created_at"]

    def __str__(self) -> str:
        return self.name


class Incident(ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    monitor = models.ForeignKey(Monitor, on_delete=models.CASCADE, related_name="incidents")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    started_at = models.DateTimeField()
    # A null resolved_at means the incident is still ongoing — that's the canonical "open" signal.
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name


class StatusPage(ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    # Slug is globally unique so the public route /status/<slug> resolves without team context.
    slug = models.CharField(max_length=64, unique=True)
    monitor_ids = ArrayField(models.UUIDField(), default=list, blank=True)
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.title
