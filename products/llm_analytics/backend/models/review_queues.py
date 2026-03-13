from django.db import models

from posthog.models.team.team import Team
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class ReviewQueue(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)

    class Meta:
        ordering = ["name", "id"]
        indexes = [
            models.Index(fields=["team", "name"], name="llma_rev_queue_name_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"],
                name="llma_rev_queue_name_uniq",
            )
        ]


class ReviewQueueItem(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    queue = models.ForeignKey(ReviewQueue, on_delete=models.CASCADE, related_name="items")
    trace_id = models.CharField(max_length=255)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["team", "queue", "created_at", "id"], name="llma_rev_q_item_queue_idx"),
            models.Index(fields=["team", "trace_id"], name="llma_rev_q_item_trace_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "trace_id"],
                name="llma_rev_q_item_trace_uniq",
            )
        ]
