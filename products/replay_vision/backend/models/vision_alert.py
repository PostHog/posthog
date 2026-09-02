from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

if TYPE_CHECKING:
    from products.replay_vision.backend.alert_state_machine import AlertSnapshot

ALERT_WINDOW_DAYS = (1, 3, 7, 14, 30)
# Selection keys that read scanner_result; failed observations never have one.
PREDICATE_SELECTION_KEYS = ("verdict", "tags", "min_score", "max_score")
DEFAULT_ALERT_WINDOW_DAYS = 1
MIN_CHECK_INTERVAL_MINUTES = 15
DEFAULT_CHECK_INTERVAL_MINUTES = 60
EVENT_RETENTION_DAYS = 90
# Undelivered outbox rows normally drain within a minute; rows this old belong to
# alerts that were disabled or deleted between insert and drain.
STALE_MATCH_RETENTION_DAYS = 30
DELIVERED_MATCH_RETENTION_DAYS = 14


class VisionAlertKind(models.TextChoices):
    # Threshold over a rolling window; carries lifecycle state (firing, snoozed, ...).
    METRIC = "metric", "Metric"
    # Fires once per matching observation via the VisionAlertMatch outbox; stateless.
    MATCH = "match", "Match"


class VisionAlertState(models.TextChoices):
    NOT_FIRING = "not_firing", "Not firing"
    FIRING = "firing", "Firing"
    PENDING_RESOLVE = "pending_resolve", "Pending resolve"
    ERRORED = "errored", "Errored"
    SNOOZED = "snoozed", "Snoozed"
    BROKEN = "broken", "Broken"


class VisionAlertMetric(models.TextChoices):
    COUNT = "count", "Count matching observations"
    AVG_SCORE = "avg_score", "Average score"  # scorer scanners only


class VisionAlertDirection(models.TextChoices):
    # Which side of the threshold breaches. Both bounds inclusive.
    ABOVE = "above", "At or above"
    BELOW = "below", "At or below"


class VisionAlertConfiguration(TeamScopedRootMixin, UUIDModel):
    """One alert on a scanner's observations, on the shared alerts platform.

    Metric alerts evaluate a rolling window on a cadence and own lifecycle state; every
    state/consecutive_failures write must go through `alert_state_machine.apply_outcome`
    (enforced by semgrep). Match alerts never leave NOT_FIRING: their delivery is driven
    by undelivered VisionAlertMatch rows, not by scheduling columns.
    """

    all_teams = models.Manager()  # noqa: DJ012 — escape hatch for cross-team Temporal access

    scanner = models.ForeignKey("replay_vision.ReplayScanner", on_delete=models.CASCADE, related_name="alerts")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)

    name = models.CharField(max_length=255)
    enabled = models.BooleanField(default=True)
    kind = models.CharField(max_length=10, choices=VisionAlertKind.choices)

    selection = models.JSONField(
        default=dict,
        help_text="Observation filter over succeeded scans: verdict (list[str]), tags (list[str]), min_score/max_score (float).",
    )

    # Metric-kind condition; null/defaults for match kind (enforced by constraints below).
    metric = models.CharField(
        max_length=20, choices=VisionAlertMetric.choices, default=VisionAlertMetric.COUNT, blank=True
    )
    direction = models.CharField(
        max_length=10, choices=VisionAlertDirection.choices, default=VisionAlertDirection.ABOVE, blank=True
    )
    threshold = models.FloatField(null=True, blank=True)
    window_days = models.PositiveSmallIntegerField(default=DEFAULT_ALERT_WINDOW_DAYS)
    check_interval_minutes = models.PositiveIntegerField(default=DEFAULT_CHECK_INTERVAL_MINUTES)

    # Lifecycle (metric kind only). Writes go through alert_state_machine.apply_outcome.
    state = models.CharField(max_length=20, choices=VisionAlertState.choices, default=VisionAlertState.NOT_FIRING)
    consecutive_failures = models.PositiveIntegerField(default=0)
    last_notified_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    first_enabled_at = models.DateTimeField(null=True, blank=True)
    snooze_until = models.DateTimeField(null=True, blank=True)
    next_check_at = models.DateTimeField(null=True, blank=True)

    # Advanced options (metric kind): N-of-M sliding window, cooldown, quiet hours.
    evaluation_periods = models.PositiveSmallIntegerField(default=1)
    datapoints_to_alarm = models.PositiveSmallIntegerField(default=1)
    cooldown_minutes = models.PositiveIntegerField(default=0)
    schedule_restriction = models.JSONField(null=True, blank=True, default=None)

    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "name"], name="vision_alert_unique_team_name"),
            # Match alerts are stateless: a lifecycle write on one is a bug that must fail
            # loudly instead of confusing the metric evaluator.
            models.CheckConstraint(
                condition=models.Q(kind=VisionAlertKind.METRIC)
                | (
                    models.Q(state=VisionAlertState.NOT_FIRING)
                    & models.Q(consecutive_failures=0)
                    & models.Q(next_check_at__isnull=True)
                ),
                name="vision_alert_match_kind_stateless",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(kind=VisionAlertKind.METRIC, threshold__isnull=False)
                    | models.Q(kind=VisionAlertKind.MATCH, threshold__isnull=True)
                ),
                name="vision_alert_metric_kind_threshold",
            ),
        ]
        indexes = [
            # Scheduler due scan is fleet-wide, so the index must not lead with team.
            models.Index(
                fields=["next_check_at"],
                name="vision_alert_scheduler_idx",
                condition=models.Q(enabled=True, kind="metric"),
            ),
            # Observation-completion hook lookup (match kind).
            models.Index(fields=["team", "scanner", "kind", "enabled"], name="vision_alert_hook_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.kind})"

    def clean(self) -> None:
        if self.datapoints_to_alarm > self.evaluation_periods:
            raise ValidationError({"datapoints_to_alarm": "Cannot exceed evaluation periods."})

    def clear_next_check(self) -> list[str]:
        """Nulls `next_check_at` so the scheduler picks this alert up on the next tick."""
        self.next_check_at = None
        return ["next_check_at"]

    def to_snapshot(self, recent_events_breached: tuple[bool, ...] | None = None) -> "AlertSnapshot":
        """Capture the fields the state machine reads for a transition decision."""
        # Deferred import: this module and alert_state_machine reference each other.
        from products.replay_vision.backend.alert_state_machine import AlertSnapshot, AlertState

        return AlertSnapshot(
            state=AlertState(self.state),
            evaluation_periods=self.evaluation_periods,
            datapoints_to_alarm=self.datapoints_to_alarm,
            cooldown_minutes=self.cooldown_minutes,
            last_notified_at=self.last_notified_at,
            snooze_until=self.snooze_until,
            consecutive_failures=self.consecutive_failures,
            recent_events_breached=(
                recent_events_breached if recent_events_breached is not None else self.get_recent_breaches()
            ),
        )

    def get_recent_breaches(self) -> tuple[bool, ...]:
        """Breach flags of the most recent CHECK events, newest first, for the N-of-M window."""
        if self.evaluation_periods <= 1:
            return ()
        rows = self.events.filter(kind=VisionAlertEvent.Kind.CHECK).order_by("-created_at")[
            : self.evaluation_periods - 1
        ]
        return tuple(row.threshold_breached for row in rows)


class VisionAlertEvent(UUIDModel):
    """Audit/check history for one VisionAlertConfiguration."""

    class Kind(models.TextChoices):
        CHECK = "check", "Check"
        RESET = "reset", "Reset"
        ENABLE = "enable", "Enable"
        DISABLE = "disable", "Disable"
        SNOOZE = "snooze", "Snooze"
        UNSNOOZE = "unsnooze", "Unsnooze"
        THRESHOLD_CHANGE = "threshold_change", "Threshold change"

    alert = models.ForeignKey(VisionAlertConfiguration, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.CHECK)
    created_at = models.DateTimeField(auto_now_add=True)

    metric_value = models.FloatField(null=True, blank=True)
    threshold_breached = models.BooleanField(default=False)
    state_before = models.CharField(max_length=20)
    state_after = models.CharField(max_length=20)
    error_message = models.TextField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["alert", "-created_at"], name="vision_alert_evt_alert_ts_idx"),
            # The retention sweep filters on created_at alone.
            models.Index(fields=["created_at"], name="vision_alert_evt_created_idx"),
        ]


class VisionAlertMatch(TeamScopedRootMixin, UUIDModel):
    """Transactional outbox row: one matching observation for one match-kind alert.

    Inserted in the observation's terminal-state transaction (exactly-once with the status
    flip); the alert-check workflow drains undelivered rows into one bundled delivery per
    alert per tick and stamps `delivered_at` only after the producer acks.
    """

    all_teams = models.Manager()  # noqa: DJ012 — escape hatch for cross-team Temporal access

    alert = models.ForeignKey(VisionAlertConfiguration, on_delete=models.CASCADE, related_name="matches")
    observation = models.ForeignKey("replay_vision.ReplayObservation", on_delete=models.CASCADE, related_name="+")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)

    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["alert", "observation"], name="vision_alert_match_unique"),
        ]
        indexes = [
            models.Index(
                fields=["alert", "created_at"],
                name="vision_alert_match_drain_idx",
                condition=models.Q(delivered_at__isnull=True),
            ),
            models.Index(fields=["delivered_at"], name="vision_alert_match_cleanup_idx"),
        ]


def selection_has_predicate(selection: dict) -> bool:
    """0 is a valid score bound, so this must not use bare truthiness."""
    return any(selection.get(key) not in (None, []) for key in PREDICATE_SELECTION_KEYS)
