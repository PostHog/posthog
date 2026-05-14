import uuid

from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.scoping.product_mixin import ProductTeamModel


class Monitor(ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    url = models.URLField(max_length=2048)
    created_at = models.DateTimeField(auto_now_add=True)

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
