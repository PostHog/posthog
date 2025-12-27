"""Django models for visual_review."""

import uuid

from django.db import models


class Snapshot(models.Model):
    """A visual snapshot captured for comparison."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    storage_path = models.CharField(max_length=1024, blank=True)

    class Meta:
        app_label = "visual_review"

    def __str__(self) -> str:
        return self.name
