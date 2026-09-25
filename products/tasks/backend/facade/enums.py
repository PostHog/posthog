from django.db import models

CHANNEL_WRITE_TYPE_CHOICES: list[str] = ["public", "private"]


class TaskRunPreviewSessionOutcome(models.TextChoices):
    READY = "ready", "Ready"
    NOT_READY = "not_ready", "Not ready"
    ENDED = "ended", "Ended"
    UNAVAILABLE = "unavailable", "Unavailable"
