from django.db import models
from django.utils.functional import Promise

from posthog.models.utils import UUIDModel

from products.notifications.backend.facade.enums import NotificationType, Priority, TargetType


def notification_type_choices() -> list[tuple[str, str | Promise]]:
    # Callable so growing the enum doesn't generate a no-op migration.
    return [(t.value, t.name) for t in NotificationType]


def priority_choices() -> list[tuple[str, str | Promise]]:
    return [(p.value, p.name) for p in Priority]


class NotificationEvent(UUIDModel):
    organization = models.ForeignKey("posthog.Organization", on_delete=models.CASCADE)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, null=True, blank=True)
    notification_type = models.CharField(max_length=32, choices=notification_type_choices)
    priority = models.CharField(max_length=16, choices=priority_choices, default=Priority.NORMAL)
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    resource_type = models.CharField(max_length=64, null=True, blank=True)
    resource_id = models.CharField(max_length=64, blank=True, default="")
    source_url = models.CharField(max_length=512, blank=True, default="")
    source_type = models.CharField(max_length=64, null=True, blank=True)
    source_id = models.CharField(max_length=64, null=True, blank=True)
    idempotency_key = models.CharField(max_length=128, null=True, blank=True)
    target_type = models.CharField(max_length=16, choices=[(t.value, t.name) for t in TargetType])
    target_id = models.CharField(max_length=64)
    resolved_user_ids = models.JSONField(default=list)
    metadata = models.JSONField(null=True, blank=True, default=None)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "idempotency_key"],
                condition=models.Q(idempotency_key__isnull=False, team__isnull=False),
                name="notification_event_team_idempotency_key_uniq",
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                condition=models.Q(idempotency_key__isnull=False, team__isnull=True),
                name="notification_event_organization_idempotency_key_uniq",
            ),
        ]
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


class NotificationArchiveState(UUIDModel):
    notification_event = models.ForeignKey(
        NotificationEvent,
        on_delete=models.CASCADE,
        related_name="archive_states",
    )
    user = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        db_constraint=False,
        related_name="notification_archive_states",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["notification_event", "user"],
                name="unique_archive_state_per_user",
            ),
        ]
