from django.db import models
from django.db.models import Q

from posthog.models.utils import CreatedMetaFields, RootTeamMixin, UpdatedMetaFields, UUIDModel


class Reminder(RootTeamMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        ERRORED = "errored", "Errored"

    class RecurrenceInterval(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"

    organization = models.ForeignKey("posthog.Organization", on_delete=models.CASCADE)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, null=True, blank=True)

    title = models.CharField(max_length=255)
    message = models.TextField(blank=True, default="")

    resource_type = models.CharField(max_length=50, null=True, blank=True)
    resource_id = models.CharField(max_length=200, null=True, blank=True)

    scheduled_at = models.DateTimeField(null=True, blank=True)
    recurrence_interval = models.CharField(max_length=20, choices=RecurrenceInterval.choices, null=True, blank=True)
    cron_expression = models.CharField(max_length=100, null=True, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    end_date = models.DateTimeField(null=True, blank=True)

    next_fire_at = models.DateTimeField(null=True, blank=True)
    last_fired_at = models.DateTimeField(null=True, blank=True)
    failure_count = models.IntegerField(default=0)
    last_error = models.TextField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    deleted = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(
                fields=["next_fire_at"],
                name="reminders_active_due_idx",
                condition=Q(status="active", deleted=False),
            ),
        ]
        constraints = [
            models.CheckConstraint(
                name="reminders_schedule_exactly_one",
                condition=(
                    Q(scheduled_at__isnull=False, recurrence_interval__isnull=True, cron_expression__isnull=True)
                    | Q(scheduled_at__isnull=True, recurrence_interval__isnull=False, cron_expression__isnull=True)
                    | Q(scheduled_at__isnull=True, recurrence_interval__isnull=True, cron_expression__isnull=False)
                ),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} (org={self.organization_id}, team={self.team_id}, user={self.created_by_id})"
