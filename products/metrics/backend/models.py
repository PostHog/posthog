"""Django models for metrics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

if TYPE_CHECKING:
    from products.metrics.backend.alert_state_machine import AlertSnapshot


class MetricsAlertConfiguration(ModelActivityMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """A threshold alert over one metric time series.

    Evaluation stays domain-specific (the metric query runner decides whether the
    latest value breached); lifecycle transitions (firing / resolving / erroring /
    snoozing / breaking) are decided by the shared alerting state machine via
    `products.metrics.backend.alert_state_machine`. State fields below are only ever
    mutated through that adapter's `apply_outcome`.
    """

    class State(models.TextChoices):
        NOT_FIRING = "not_firing", "Not firing"
        FIRING = "firing", "Firing"
        ERRORED = "errored", "Errored"
        SNOOZED = "snoozed", "Snoozed"
        BROKEN = "broken", "Broken"

    class ThresholdOperator(models.TextChoices):
        ABOVE = "above", "Above"
        BELOW = "below", "Below"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=255)
    enabled = models.BooleanField(default=True)

    # What is evaluated — a single metric selection mirroring MetricQueryClause.
    # `aggregation` is one of facade.enums.MetricAggregation; `quantile` is only
    # required when the aggregation is quantile-based.
    metric_name = models.CharField(max_length=512)
    aggregation = models.CharField(max_length=32)
    quantile = models.FloatField(null=True, blank=True)
    # List of {key, op, value, scope} label predicates (facade MetricFilter shape).
    filters = models.JSONField(default=list, blank=True)
    # List of {key, scope} labels to split the series by (facade MetricGroupBy shape).
    # group_by enriches the breach message and check history; in this singleton phase
    # the alert still holds ONE state across all groups (grouped runtime alerts are a
    # later phase — see the unified alerting RFC).
    group_by = models.JSONField(default=list, blank=True)

    # Threshold
    threshold_value = models.FloatField(default=0)
    threshold_operator = models.CharField(
        max_length=10,
        choices=ThresholdOperator.choices,
        default=ThresholdOperator.ABOVE,
    )

    # Window & scheduling
    window_minutes = models.PositiveIntegerField(default=5)
    check_interval_minutes = models.PositiveIntegerField(default=5)

    # N-of-M evaluation (AWS CloudWatch naming convention):
    # evaluation_periods = M, datapoints_to_alarm = N
    evaluation_periods = models.PositiveIntegerField(default=1)
    datapoints_to_alarm = models.PositiveIntegerField(default=1)

    # Cooldown & snooze
    cooldown_minutes = models.PositiveIntegerField(default=0)
    snooze_until = models.DateTimeField(null=True, blank=True)
    schedule_restriction = models.JSONField(null=True, blank=True, default=None)

    # State (mutated only via the alert_state_machine adapter)
    state = models.CharField(
        max_length=20,
        choices=State.choices,
        default=State.NOT_FIRING,
    )
    consecutive_failures = models.PositiveIntegerField(default=0)

    # Tracking
    next_check_at = models.DateTimeField(null=True, blank=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "metrics_metricsalertconfiguration"
        indexes = [
            models.Index(
                fields=["team_id", "next_check_at", "enabled"],
                name="metrics_alert_scheduler_idx",
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

    def to_snapshot(self, recent_events_breached: tuple[bool, ...] | None = None) -> AlertSnapshot:
        """Capture the fields the state machine reads for a transition decision."""
        from products.metrics.backend.alert_state_machine import AlertSnapshot, AlertState  # noqa: PLC0415

        return AlertSnapshot(
            state=AlertState(self.state),
            evaluation_periods=self.evaluation_periods,
            datapoints_to_alarm=self.datapoints_to_alarm,
            cooldown_minutes=self.cooldown_minutes,
            last_notified_at=self.last_notified_at,
            snooze_until=self.snooze_until,
            consecutive_failures=self.consecutive_failures,
            recent_events_breached=recent_events_breached
            if recent_events_breached is not None
            else self.get_recent_breaches(),
        )

    def get_recent_breaches(self) -> tuple[bool, ...]:
        """Last M non-errored check events' threshold_breached values, newest first."""
        return tuple(
            MetricsAlertEvent.objects.filter(
                alert=self,
                kind=MetricsAlertEvent.Kind.CHECK,
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


class MetricsAlertEvent(UUIDModel):
    """Audit + evaluation history for a metrics alert.

    CHECK rows feed the N-of-M evaluator; the other kinds are user-initiated
    control-plane transitions kept for forensics.
    """

    class Kind(models.TextChoices):
        CHECK = "check", "Check"
        RESET = "reset", "Reset"
        ENABLE = "enable", "Enable"
        DISABLE = "disable", "Disable"
        SNOOZE = "snooze", "Snooze"
        UNSNOOZE = "unsnooze", "Unsnooze"
        THRESHOLD_CHANGE = "threshold_change", "Threshold change"
        BROKEN_CONFIG = "broken_config", "Broken config"

    alert = models.ForeignKey(
        MetricsAlertConfiguration,
        on_delete=models.CASCADE,
        related_name="events",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.CHECK)

    # Evaluation result for CHECK rows
    value = models.FloatField(null=True, blank=True)
    threshold_breached = models.BooleanField(default=False)
    # The breaching group's labels when group_by is set (message enrichment).
    labels = models.JSONField(default=dict, blank=True)

    state_before = models.CharField(max_length=20)
    state_after = models.CharField(max_length=20)
    error_message = models.TextField(null=True, blank=True)
    query_duration_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "metrics_metricsalertevent"
        indexes = [
            models.Index(fields=["alert", "-created_at"], name="metrics_alert_evt_alert_ts_idx"),
        ]

    def __str__(self) -> str:
        return f"MetricsAlertEvent({self.kind}) for {self.alert_id} at {self.created_at}"
