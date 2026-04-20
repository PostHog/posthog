from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel
from posthog.utils import generate_short_id

if TYPE_CHECKING:
    from products.logs.backend.alert_state_machine import AlertSnapshot

# Upper bound on LogsAlertConfiguration.evaluation_periods. Doubles as the per-alert
# cap on retained OK event rows — the N-of-M evaluator never reads more than this many
# non-errored rows per alert, so older OK rows are pruned. Mirrored in the serializer's
# max_value so the two can't drift.
MAX_EVALUATION_PERIODS = 10


class LogsView(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    short_id = models.CharField(max_length=12, blank=True, default=generate_short_id)
    name = models.CharField(max_length=400)
    filters = models.JSONField(default=dict)
    pinned = models.BooleanField(default=False)

    class Meta:
        db_table = "logs_logsview"
        unique_together = ("team", "short_id")
        indexes = [
            models.Index(fields=["team_id", "-created_at"], name="logs_view_team_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} (Team: {self.team})"


class LogsAlertConfiguration(ModelActivityMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    class State(models.TextChoices):
        NOT_FIRING = "not_firing", "Not firing"
        FIRING = "firing", "Firing"
        PENDING_RESOLVE = "pending_resolve", "Pending resolve"
        ERRORED = "errored", "Errored"
        SNOOZED = "snoozed", "Snoozed"
        BROKEN = "broken", "Broken"

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

    def clear_next_check(self) -> list[str]:
        """Nulls `next_check_at` so the scheduler picks this alert up on the next tick.
        Returns modified fields for `save(update_fields=...)`.
        """
        self.next_check_at = None
        return ["next_check_at"]

    def to_snapshot(self) -> AlertSnapshot:
        """Capture the fields the state machine reads for a transition decision."""
        from products.logs.backend.alert_state_machine import AlertSnapshot, AlertState

        return AlertSnapshot(
            state=AlertState(self.state),
            evaluation_periods=self.evaluation_periods,
            datapoints_to_alarm=self.datapoints_to_alarm,
            cooldown_minutes=self.cooldown_minutes,
            last_notified_at=self.last_notified_at,
            snooze_until=self.snooze_until,
            consecutive_failures=self.consecutive_failures,
            recent_events_breached=self.get_recent_breaches(),
        )

    def get_recent_breaches(self) -> tuple[bool, ...]:
        """Last M non-errored check events' threshold_breached values, newest first."""
        return tuple(
            LogsAlertEvent.objects.filter(
                alert=self,
                kind=LogsAlertEvent.Kind.CHECK,
                error_message__isnull=True,
            )
            .order_by("-created_at")
            .values_list("threshold_breached", flat=True)[: self.evaluation_periods]
        )

    def clean(self) -> None:
        super().clean()
        if self.datapoints_to_alarm > self.evaluation_periods:
            raise ValidationError(
                f"datapoints_to_alarm cannot exceed evaluation_periods ({self.datapoints_to_alarm} > {self.evaluation_periods})"
            )


class LogsAlertCheck(UUIDModel):
    """Defunct — kept in sync with the physical table `logs_logsalertcheck`.

    All production reads and writes go through `LogsAlertEvent` (the new table). This
    shell class exists solely to match Django's model state with the legacy table
    created by `0001_initial.py`. PR 4 will drop the table and remove this class.
    """

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


class LogsAlertEvent(UUIDModel):
    # Events (errored, breached, state-transition rows) retained this long for forensics.
    # OK rows are capped by count (MAX_EVALUATION_PERIODS per alert) rather than by time.
    EVENT_RETENTION_DAYS = 90

    class Kind(models.TextChoices):
        # Worker-produced row from evaluating the ClickHouse check query. Only CHECK rows
        # feed the N-of-M evaluator and are eligible for the inline prune. Control-plane
        # kinds are reserved for user-initiated state transitions; writers are added in a
        # follow-up PR (see spike 4.7). Every read path must filter by kind=CHECK to keep
        # control-plane rows out of evaluator and prune windows.
        CHECK = "check", "Check"
        RESET = "reset", "Reset"
        ENABLE = "enable", "Enable"
        DISABLE = "disable", "Disable"
        SNOOZE = "snooze", "Snooze"
        UNSNOOZE = "unsnooze", "Unsnooze"
        THRESHOLD_CHANGE = "threshold_change", "Threshold change"

    alert = models.ForeignKey(
        LogsAlertConfiguration,
        on_delete=models.CASCADE,
        related_name="events",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.CHECK)
    created_at = models.DateTimeField(auto_now_add=True)
    result_count = models.PositiveIntegerField(null=True, blank=True)
    threshold_breached = models.BooleanField()
    state_before = models.CharField(max_length=20)
    state_after = models.CharField(max_length=20)
    error_message = models.TextField(null=True, blank=True)
    query_duration_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "logs_logsalertevent"

    def __str__(self) -> str:
        return f"LogsAlertEvent for {self.alert.name} at {self.created_at}"

    @classmethod
    def clean_up_old_events(cls) -> int:
        """Delete every event row older than EVENT_RETENTION_DAYS.

        In steady state this only touches errored rows and state-transition rows: the
        Temporal activity caps non-event rows to MAX_EVALUATION_PERIODS per alert
        inline. Rows from silent or disabled alerts also age out through this path.
        """
        oldest = datetime.now(UTC) - timedelta(days=cls.EVENT_RETENTION_DAYS)
        count, _ = cls.objects.filter(created_at__lt=oldest).delete()
        return count
