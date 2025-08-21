from django.db import models

from posthog.models.team.team import Team
from posthog.models.utils import (
    CreatedMetaFields,
    DeletedMetaFields,
    UpdatedMetaFields,
    UUIDModel,
)


class Dataset(UUIDModel, CreatedMetaFields, UpdatedMetaFields, DeletedMetaFields):
    class Meta:
        ordering = ["-created_at", "id"]
        indexes = [
            models.Index(fields=["team", "-created_at", "id"]),
        ]

    name = models.CharField(max_length=400)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    description = models.TextField(null=True, blank=True)
    metadata = models.JSONField(null=True, blank=True)


class DatasetItem(UUIDModel, CreatedMetaFields, UpdatedMetaFields, DeletedMetaFields):
    class Meta:
        ordering = ["-created_at", "id"]
        indexes = [
            models.Index(fields=["dataset", "-created_at", "id"]),
        ]

    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="items")
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    input = models.JSONField(null=True, blank=True)
    output = models.JSONField(null=True, blank=True)
    metadata = models.JSONField(null=True, blank=True)
    ref_trace_id = models.CharField(max_length=255, null=True, blank=True)
    ref_trace_timestamp = models.DateTimeField(null=True, blank=True)
    ref_span_id = models.CharField(max_length=255, null=True, blank=True)
