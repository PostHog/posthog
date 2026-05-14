import uuid

from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.scoping.product_mixin import ProductTeamModel


class Monitor(ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    url = models.URLField(max_length=2048)
    created_at = models.DateTimeField(auto_now_add=True)
    # User-controlled display order in the list view. Backfilled per-team from
    # creation order; smaller values render first.
    display_order = models.BigIntegerField(default=0, db_index=True)

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
