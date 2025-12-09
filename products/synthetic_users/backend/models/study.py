from django.db import models

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class Study(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["team", "-created_at"]),
        ]

    objects: models.Manager["Study"]

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    name = models.CharField(max_length=400)
    audience_description = models.TextField()
    research_goal = models.TextField()
    target_url = models.URLField(max_length=2048)
