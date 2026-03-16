from django.db import models

from posthog.models.utils import UUIDModel


class NotificationEvent(UUIDModel):
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

    class TargetType(models.TextChoices):
        USER = "user"
        TEAM = "team"
        ORGANIZATION = "organization"
        ROLE = "role"

    organization = models.ForeignKey("posthog.Organization", on_delete=models.CASCADE)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, null=True, blank=True)
    notification_type = models.CharField(max_length=32, choices=NotificationType.choices)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    resource_type = models.CharField(max_length=64, null=True, blank=True)
    resource_id = models.CharField(max_length=64, blank=True, default="")
    source_url = models.CharField(max_length=512, blank=True, default="")
    target_type = models.CharField(max_length=16, choices=TargetType.choices)
    target_id = models.CharField(max_length=64)
    resolved_user_ids = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
        ]


class NotificationReadState(UUIDModel):
    notification_event = models.ForeignKey(
        NotificationEvent,
        on_delete=models.CASCADE,
        related_name="read_states",
    )
    user = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="notification_read_states",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["notification_event", "user"],
                name="unique_read_state_per_user",
            ),
        ]
