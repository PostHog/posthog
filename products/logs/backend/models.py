from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class LogsAlertConfiguration(ModelActivityMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    class State(models.TextChoices):
        NOT_FIRING = "not_firing", "Not firing"
        FIRING = "firing", "Firing"
        PENDING_RESOLVE = "pending_resolve", "Pending resolve"
        ERRORED = "errored", "Errored"
        SNOOZED = "snoozed", "Snoozed"

    class ThresholdOperator(models.TextChoices):
        ABOVE = "above", "Above"
        BELOW = "below", "Below"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    enabled = models.BooleanField(default=True)

    # Filter criteria — subset of LogsViewerFilters (excludes dateRange).
    # Expected shape:
    # {
    #     "severityLevels": list[str],
    #     "serviceNames": list[str],
    #     "filterGroup": {...},
    # }
    filters = models.JSONField(default=dict)

    # Threshold
    threshold_count = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    threshold_operator = models.CharField(
        max_length=10,
        choices=ThresholdOperator.choices,
        default=ThresholdOperator.ABOVE,
    )

    # Window & scheduling
    window_minutes = models.PositiveIntegerField(default=5)
    check_interval_minutes = models.PositiveIntegerField(default=1)

    # State
    state = models.CharField(
        max_length=20,
        choices=State.choices,
        default=State.NOT_FIRING,
    )

    # N-of-M evaluation (AWS CloudWatch naming convention).
    # evaluation_periods = M, datapoints_to_alarm = N
    evaluation_periods = models.PositiveIntegerField(default=1)
    datapoints_to_alarm = models.PositiveIntegerField(default=1)

    # Cooldown & snooze
    cooldown_minutes = models.PositiveIntegerField(default=0)
    snooze_until = models.DateTimeField(null=True, blank=True)

    # Scheduling & tracking
    next_check_at = models.DateTimeField(null=True, blank=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "logs_logsalertconfiguration"
        indexes = [
            models.Index(
                fields=["team_id", "next_check_at", "enabled"],
                name="logs_alert_scheduler_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} (Team: {self.team})"

    def clean(self) -> None:
        super().clean()
        if self.datapoints_to_alarm > self.evaluation_periods:
            raise ValidationError(
                f"datapoints_to_alarm cannot exceed evaluation_periods ({self.datapoints_to_alarm} > {self.evaluation_periods})"
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.enabled:
            self.state = self.State.NOT_FIRING
            if "update_fields" in kwargs and "state" not in kwargs["update_fields"]:
                kwargs["update_fields"] = [*kwargs["update_fields"], "state"]

        super().save(*args, **kwargs)


class LogsAlertCheck(UUIDModel):
    RETENTION_DAYS = 14

    alert = models.ForeignKey(
        LogsAlertConfiguration,
        on_delete=models.CASCADE,
        related_name="checks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    result_count = models.PositiveIntegerField(null=True, blank=True)
    threshold_breached = models.BooleanField()
    state_before = models.CharField(max_length=20)
    state_after = models.CharField(max_length=20)
    error_message = models.TextField(null=True, blank=True)
    query_duration_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "logs_logsalertcheck"

    def __str__(self) -> str:
        return f"LogsAlertCheck for {self.alert.name} at {self.created_at}"

    @classmethod
    def clean_up_old_checks(cls) -> int:
        oldest_allowed = datetime.now(UTC) - timedelta(days=cls.RETENTION_DAYS)
        count, _ = cls.objects.filter(created_at__lt=oldest_allowed).delete()
        return count
