from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.manager import TeamScopedManager
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.team.extensions import register_team_extension_signal
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel
from posthog.utils import generate_short_id

if TYPE_CHECKING:
    from posthog.models.user import User

    from products.logs.backend.alert_state_machine import AlertSnapshot

logger = logging.getLogger(__name__)

# Default log attribute key whose value matches a PostHog person's distinct_id. Mirrors
# the convention documented at https://posthog.com/docs/logs/link-session-replay: the
# posthog-js / posthog-react-native SDKs auto-attach `posthogDistinctId` to every log
# they emit, and the docs instruct OTel-emitting backends to set the same key. Customers
# whose pipeline uses a different key can override via the `logs_config` endpoint.
DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEY = "posthogDistinctId"


class TeamLogsConfig(models.Model):
    # Plain `models.Model` (not `TeamScopedRootMixin`) — log emission and ingestion
    # are per-environment, and so is this config. Inheriting the root-mixin would
    # rewrite writes to the parent project on save, letting a member of one child
    # environment mutate config that affects sibling environments they may not have
    # access to. Mirrors the `TeamExperimentsConfig` precedent.
    team = models.OneToOneField("posthog.Team", on_delete=models.CASCADE, primary_key=True)

    # Log attribute key whose value matches a PostHog person's distinct_id. Used by the
    # person profile Logs tab and the `query-logs` MCP tool to filter logs to a single
    # user without needing per-team prompt engineering.
    logs_distinct_id_attribute_key = models.CharField(
        max_length=200,
        default=DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEY,
        db_default=DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEY,
    )


register_team_extension_signal(TeamLogsConfig, logger=logger)


class LogsUserConfigManager(TeamScopedManager["LogsUserConfig"]):
    """Binds the *user* dimension on top of team scoping.

    `TeamScopedRootMixin`'s manager fail-closes the *team* dimension but does NOT enforce the user —
    a bare `.get(pk=...)` / `.filter(...)` in request context (the normal DRF path) could resolve
    another member's row in the same project (IDOR). Read through `for_user`; writes must pass
    `user=` explicitly. Never use bare `.objects.get` / `.filter` without binding the user.
    """

    def for_user(self, user: User) -> models.QuerySet[LogsUserConfig]:
        # Team scope is applied automatically by the parent manager; we add the user filter it omits.
        # Outside request context, compose with for_team: `objects.for_team(team_id).filter(user=user)`.
        return self.filter(user=user)


class LogsUserConfig(TeamScopedRootMixin, UpdatedMetaFields, UUIDModel):
    """A single user's logs-rail configuration for a project — one row per (team, user). Currently
    holds the custom facets they pinned into the rail's "Custom" group.

    All access MUST bind the user, not just the team: read via `LogsUserConfig.objects.for_user(user)`
    and pass `user=` explicitly on writes. Team scoping alone does not isolate per-user rows — see
    `LogsUserConfigManager`."""

    # Unlike TeamLogsConfig, this is a per-*user* preference, so the cross-environment mutation
    # concern that keeps that model off the root mixin doesn't apply: a user can only edit their
    # own config. TeamScopedRootMixin therefore scopes it to the project (facets follow the user
    # across environments) and starts it fail-closed, as required for new team-scoped models.
    #
    # db_constraint=False on both FKs: posthog_team and posthog_user are hot tables, so a real FK
    # constraint here would lock them on CreateModel (blocked by HotTableAlterPolicy). The team_id
    # column (for scoping) and app-level cascade are retained.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    user = models.ForeignKey(
        "posthog.User", on_delete=models.CASCADE, related_name="logs_user_configs", db_constraint=False
    )
    # list of { "key": str, "attribute_type": "resource" | "log" }
    custom_facets = models.JSONField(default=list)

    objects = LogsUserConfigManager()  # type: ignore[assignment, misc]

    class Meta:
        db_table = "logs_logsuserconfig"
        constraints = [
            models.UniqueConstraint(fields=["team", "user"], name="logs_user_config_team_user_uniq"),
        ]

    def __str__(self) -> str:
        return f"LogsUserConfig(team={self.team_id}, user={self.user_id})"


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

    # Scheduling & tracking
    next_check_at = models.DateTimeField(null=True, blank=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    first_enabled_at = models.DateTimeField(null=True, blank=True)

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

    def to_snapshot(self, recent_events_breached: tuple[bool, ...] | None = None) -> AlertSnapshot:
        """Capture the fields the state machine reads for a transition decision.

        `recent_events_breached` lets the caller pass in the M-of-N window directly
        (e.g. derived from a single bucketed CH query). When omitted, falls back to
        reading historical CHECK rows via `get_recent_breaches` — kept for back-compat
        with code paths that haven't switched to the bucketed eval yet.
        """
        from products.logs.backend.alert_state_machine import AlertSnapshot, AlertState

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
        BROKEN_CONFIG = "broken_config", "Broken config"

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
        indexes = [
            models.Index(fields=["alert", "-created_at"], name="logs_alert_event_alert_ts_idx"),
        ]

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


class LogsExclusionRule(ModelActivityMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """User-defined rules to drop or exclude log lines before storage (evaluated in ingestion when enabled)."""

    class RuleType(models.TextChoices):
        SEVERITY_SAMPLING = "severity_sampling", "Severity-based reduction"
        PATH_DROP = "path_drop", "Path exclusion"
        RATE_LIMIT = "rate_limit", "Rate limit"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    enabled = models.BooleanField(default=False)
    priority = models.PositiveIntegerField(
        default=0,
        help_text="Lower values run first; first matching rule wins. Ties use created_at ascending (same as ingestion query order).",
    )
    rule_type = models.CharField(max_length=32, choices=RuleType.choices)
    scope_service = models.CharField(max_length=512, null=True, blank=True)
    scope_path_pattern = models.CharField(max_length=1024, null=True, blank=True)
    scope_attribute_filters = models.JSONField(default=list)
    config = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "logs_logsexclusionrule"
        indexes = [
            models.Index(fields=["team_id", "enabled", "priority"], name="logs_exclusion_team_en_pr_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} (team={self.team_id})"
