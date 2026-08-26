"""Django models for tracing."""

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel
from posthog.utils import generate_short_id

if TYPE_CHECKING:
    from products.tracing.backend.alert_state_machine import AlertSnapshot

# Upper bound on the N-of-M evaluation window (evaluation_periods / datapoints_to_alarm),
# enforced by the API serializer. Mirrors `products/logs/backend/models.py`.
MAX_EVALUATION_PERIODS = 10

# Define your models here
# Important:
# - Keep models thin, no business logic, use logic.py instead
# - Use types from facade/contracts.py or facade/enums.py where applicable
# - Do not use ForeignKeys to models outside this app unless allowed, as you will make implicit dependencies.
# - If you make a ForeignKey to a common model, disallow reverse relations with related_name='+'


class TracingView(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    """A saved set of tracing filters (date range, services, attribute filters, sort, view mode).

    Content-only storage — `filters` mirrors the frontend `TracingFilters` shape; restoring a view
    just replays those filters into `tracingFiltersLogic`.
    """

    # FKs to the hot posthog_team / posthog_user tables use db_constraint=False so creating this
    # table takes no lock on those parents; the real constraints are added lock-free via
    # AddForeignKeyNotValid in the migration. created_by overrides CreatedMetaFields for the same reason.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    # Human-friendly id used in the API/URL instead of exposing the UUID primary key.
    short_id = models.CharField(max_length=12, blank=True, default=generate_short_id)
    name = models.CharField(max_length=400)
    filters = models.JSONField(default=dict)
    pinned = models.BooleanField(default=False)

    class Meta:
        db_table = "tracing_tracingview"
        unique_together = ("team", "short_id")
        indexes = [
            models.Index(fields=["team_id", "-created_at"], name="tracing_view_team_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} (Team: {self.team})"


class TracingAlertConfiguration(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    """A threshold alert on `trace_spans`. Mirrors `LogsAlertConfiguration`
    (`products/logs/backend/models.py`) field-for-field — see
    `products/tracing/backend/alert_state_machine.py` for the shared lifecycle wiring.
    """

    class AlertType(models.TextChoices):
        THRESHOLD = "threshold", "Threshold"
        # ANOMALY is reserved for a future statistical-anomaly type backed by
        # products/apm's spike/drop/silence detector, once that product builds a
        # persistence ("filing") layer for it. Do not implement ANOMALY without one.

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

    # FKs to the hot posthog_team / posthog_user tables use db_constraint=False so creating
    # this table takes no lock on those parents; the real constraints are added lock-free
    # via AddForeignKeyNotValid in the migration. created_by overrides CreatedMetaFields
    # for the same reason.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    name = models.CharField(max_length=255)
    enabled = models.BooleanField(default=True)
    alert_type = models.CharField(max_length=20, choices=AlertType, default=AlertType.THRESHOLD)

    # Filter criteria against trace_spans.
    # Expected shape:
    # {
    #     "serviceNames": list[str],
    #     "errorOnly": bool,
    #     "filterGroup": {...},
    # }
    filters = models.JSONField(default=dict)

    # Threshold
    threshold_count = models.PositiveIntegerField(default=100)
    threshold_operator = models.CharField(
        max_length=10,
        choices=ThresholdOperator,
        default=ThresholdOperator.ABOVE,
    )

    # Window & scheduling
    window_minutes = models.PositiveIntegerField(default=5)
    check_interval_minutes = models.PositiveIntegerField(default=5)

    # State
    state = models.CharField(
        max_length=20,
        choices=State,
        default=State.NOT_FIRING,
    )

    # N-of-M evaluation (AWS CloudWatch naming convention).
    # evaluation_periods = M, datapoints_to_alarm = N
    evaluation_periods = models.PositiveIntegerField(default=1)
    datapoints_to_alarm = models.PositiveIntegerField(default=1)

    # Cooldown & snooze
    cooldown_minutes = models.PositiveIntegerField(default=0)
    snooze_until = models.DateTimeField(null=True, blank=True)
    schedule_restriction = models.JSONField(null=True, blank=True, default=None)

    # Scheduling & tracking
    next_check_at = models.DateTimeField(null=True, blank=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    first_enabled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tracing_tracingalertconfiguration"
        indexes = [
            models.Index(
                fields=["team_id", "next_check_at", "enabled"],
                name="tracing_alert_scheduler_idx",
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

    def to_snapshot(self, recent_events_breached: tuple[bool, ...] | None = None) -> "AlertSnapshot":
        """Capture the fields the state machine reads for a transition decision.

        `recent_events_breached` lets the caller pass in the M-of-N window directly
        (e.g. derived from a single bucketed CH query). When omitted, falls back to
        reading historical CHECK rows via `get_recent_breaches`.
        """
        from products.tracing.backend.alert_state_machine import AlertSnapshot, AlertState

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
            TracingAlertEvent.objects.filter(
                alert=self,
                kind=TracingAlertEvent.Kind.CHECK,
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


class TracingAlertEvent(UUIDModel):
    """One row per check/control-plane action against a `TracingAlertConfiguration`.
    Mirrors `LogsAlertEvent` (`products/logs/backend/models.py`).
    """

    EVENT_RETENTION_DAYS = 90

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
        TracingAlertConfiguration,
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
        db_table = "tracing_tracingalertevent"
