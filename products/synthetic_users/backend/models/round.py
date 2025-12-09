from django.db import models

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class Round(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        GENERATING = "generating", "Generating"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["study", "-created_at"]),
        ]

    objects: models.Manager["Round"]

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    study = models.ForeignKey(
        "synthetic_users.Study",
        on_delete=models.CASCADE,
        related_name="rounds",
    )
    round_number = models.PositiveIntegerField()
    session_count = models.PositiveIntegerField(default=0)
    notes = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    summary = models.TextField(null=True, blank=True)
