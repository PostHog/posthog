from django.db import models

from posthog.models.utils import UUIDModel

from products.notifications.backend.facade.enums import NotificationType, Priority, TargetType


class NotificationEvent(UUIDModel):
    organization = models.ForeignKey("posthog.Organization", on_delete=models.CASCADE)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, null=True, blank=True)
    notification_type = models.CharField(max_length=32, choices=[(t.value, t.name) for t in NotificationType])
    priority = models.CharField(max_length=16, choices=[(p.value, p.name) for p in Priority], default=Priority.NORMAL)
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    resource_type = models.CharField(max_length=64, null=True, blank=True)
    resource_id = models.CharField(max_length=64, blank=True, default="")
    source_url = models.CharField(max_length=512, blank=True, default="")
    target_type = models.CharField(max_length=16, choices=[(t.value, t.name) for t in TargetType])
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
