from django.db import models

from posthog.models.utils import UUIDModel


class Notification(UUIDModel):
    class NotificationType(models.TextChoices):
        COMMENT_MENTION = "comment_mention"
        ALERT_FIRING = "alert_firing"
        APPROVAL_REQUESTED = "approval_requested"
        APPROVAL_RESOLVED = "approval_resolved"
        PIPELINE_FAILURE = "pipeline_failure"
        ISSUE_ASSIGNED = "issue_assigned"

    class Priority(models.TextChoices):
        NORMAL = "normal"
        URGENT = "urgent"

    recipient = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    notification_type = models.CharField(max_length=32, choices=NotificationType.choices)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    source_type = models.CharField(max_length=64, blank=True, default="")
    source_id = models.CharField(max_length=64, blank=True, default="")
    source_url = models.CharField(max_length=512, blank=True, default="")
    actor = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "read", "-created_at"]),
        ]
