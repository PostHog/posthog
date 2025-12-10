from django.db import models

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class Session(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        GENERATING = "generating", "Generating"
        NAVIGATING = "navigating", "Navigating"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class Sentiment(models.TextChoices):
        POSITIVE = "positive", "Positive"
        NEUTRAL = "neutral", "Neutral"
        NEGATIVE = "negative", "Negative"

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["round", "-created_at"]),
        ]

    objects: models.Manager["Session"]

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    round = models.ForeignKey(
        "synthetic_users.Round",
        on_delete=models.CASCADE,
        related_name="sessions",
    )

    # Generated persona
    name = models.CharField(max_length=200)
    archetype = models.CharField(max_length=200)
    background = models.TextField()
    traits = models.JSONField(default=list)  # list of strings

    # Generated plan
    plan = models.TextField(blank=True)

    # Execution
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    session_replay_url = models.URLField(max_length=2048, null=True, blank=True)

    # Stream of consciousness - list of thought strings
    thought_action_log = models.JSONField(default=list)  # list of strings

    # Results
    experience_writeup = models.TextField(null=True, blank=True)
    key_insights = models.JSONField(default=list)  # list of strings
    sentiment = models.CharField(
        max_length=20,
        choices=Sentiment.choices,
        null=True,
        blank=True,
    )
