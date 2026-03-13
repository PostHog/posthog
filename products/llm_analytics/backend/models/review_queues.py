from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from posthog.models.team.team import Team
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UpdatedMetaFields, UUIDModel


class ReviewQueue(UUIDModel, CreatedMetaFields, UpdatedMetaFields, DeletedMetaFields):
    objects: models.Manager["ReviewQueue"]

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
                condition=Q(deleted=False),
                name="llma_rev_queue_name_uniq",
            )
        ]

    @transaction.atomic
    def soft_delete(self) -> None:
        if self.deleted:
            return

        now = timezone.now()
        self.deleted = True
        self.deleted_at = now
        self.save(update_fields=["deleted", "deleted_at", "updated_at"])

        ReviewQueueItem.objects.filter(queue=self, deleted=False).update(deleted=True, deleted_at=now, updated_at=now)

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        raise Exception("Cannot hard delete ReviewQueue. Use soft_delete() instead.")


class ReviewQueueItem(UUIDModel, CreatedMetaFields, UpdatedMetaFields, DeletedMetaFields):
    objects: models.Manager["ReviewQueueItem"]

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
                condition=Q(deleted=False),
                name="llma_rev_q_item_trace_uniq",
            )
        ]

    def soft_delete(self) -> None:
        if self.deleted:
            return

        self.deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted", "deleted_at", "updated_at"])

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        raise Exception("Cannot hard delete ReviewQueueItem. Use soft_delete() instead.")
