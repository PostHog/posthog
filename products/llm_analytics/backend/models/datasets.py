from django.contrib.postgres.indexes import GinIndex
from django.db import models

from posthog.models.team.team import Team
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UpdatedMetaFields, UUIDModel


class Dataset(UUIDModel, CreatedMetaFields, UpdatedMetaFields, DeletedMetaFields):
    class Meta:
        ordering = ["-created_at", "id"]
        indexes = [
            models.Index(fields=["team", "-created_at", "id"]),
            models.Index(fields=["team", "-updated_at", "id"]),
            GinIndex(name="llm_dataset_name_trgm", fields=["name"], opclasses=["gin_trgm_ops"]),
            GinIndex(name="llm_dataset_desc_trgm", fields=["description"], opclasses=["gin_trgm_ops"]),
        ]

    objects: models.Manager["Dataset"]

    name = models.CharField(max_length=400)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    description = models.TextField(null=True, blank=True)
    metadata = models.JSONField(null=True, blank=True)


class DatasetItem(UUIDModel, CreatedMetaFields, UpdatedMetaFields, DeletedMetaFields):
    class Meta:
        ordering = ["-created_at", "id"]
        indexes = [
            models.Index(fields=["team", "dataset", "-created_at", "id"]),
            models.Index(fields=["team", "dataset", "-updated_at", "id"]),
            GinIndex(name="llm_dataset_item_input_trgm", fields=["input"], opclasses=["gin_trgm_ops"]),
            GinIndex(name="llm_dataset_item_output_trgm", fields=["output"], opclasses=["gin_trgm_ops"]),
            GinIndex(name="llm_dataset_item_metadata_trgm", fields=["metadata"], opclasses=["gin_trgm_ops"]),
        ]

    objects: models.Manager["DatasetItem"]

    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="items")
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    input = models.JSONField(null=True, blank=True)
    output = models.JSONField(null=True, blank=True)
    metadata = models.JSONField(null=True, blank=True)
    ref_trace_id = models.CharField(max_length=255, null=True, blank=True)
    ref_trace_timestamp = models.DateTimeField(null=True, blank=True)
    ref_span_id = models.CharField(max_length=255, null=True, blank=True)
