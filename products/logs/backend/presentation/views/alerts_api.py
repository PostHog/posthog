import datetime as dt
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Final, Literal, TypedDict, cast, overload
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import F, Manager, OuterRef, Prefetch, Q, QuerySet, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone

from drf_spectacular.utils import extend_schema, extend_schema_field, extend_schema_view
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import LogsAlertFilters

from posthog.api.fields import RepeatedOrCommaSeparatedListField
from posthog.api.pagination import stable_queryset_ordering
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.dataclasses import frozen
from posthog.event_usage import report_user_action
from posthog.exceptions import as_drf_validation_error
from posthog.exceptions_capture import capture_exception
from posthog.helpers.impersonation import is_impersonated
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.user import User
from posthog.utils import relative_date_parse

from products.alerts.backend.facade.destinations import (
    build_alert_destination_config,
    configured_destination_template_ids,
    create_alert_destination_hog_functions,
    customized_alert_destination_ids,
    destination_handles_event_kind,
    destination_template_id,
    list_alert_destination_groups,
    owned_alert_destination_ids,
    redact_destination_data,
    soft_delete_alert_destinations,
    validate_destination_data,
)
from products.alerts_platform.backend.facade.api import (
    history_by_legacy_id,
    recent_destination_sends,
    reset_broken,
    runtime_by_legacy_id,
)
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertDestinationValidationError,
    DestinationType,
    Grouping,
    InvalidPlatformAlertEdit,
    PagerDutyRegion,
    PagerDutySeverity,
    PlatformAlertHistory,
    PlatformAlertRuntime,
)
from products.alerts_platform.backend.facade.enums import DeliveryPath, PlatformAlertState
from products.alerts_platform.backend.facade.scheduling import validate_and_normalize_schedule_restriction
from products.alerts_platform.backend.presentation.views.platform_alert import GroupingSerializer
from products.alerts_platform.backend.presentation.views.schedule_restriction import ScheduleRestrictionField
from products.logs.backend.alert_check_query import AlertCheckQuery, BucketedCount
from products.logs.backend.alert_destinations import (
    EVENT_KIND_CONFIG,
    EVENT_KINDS,
    LOGS_ALERT_EVENT_IDS,
    LOGS_ALERT_SLACK_CONTEXT_ELEMENTS,
    LOGS_DESTINATION_TYPES,
)
from products.logs.backend.alert_state_machine import (
    AlertCheckOutcome,
    AlertSnapshot,
    AlertState,
    CheckResult,
    IncidentCloseReason,
    InvalidTransition,
    NotificationAction,
    apply_disable,
    apply_enable,
    apply_outcome,
    apply_snooze,
    apply_threshold_change,
    apply_unsnooze,
    apply_user_reset,
    evaluate_alert_check,
)
from products.logs.backend.facade.api import (
    ALLOWED_WINDOW_MINUTES,
    MAX_MERGED_EVENT_ROWS,
    AlertLimitReached,
    PlatformCheckRow,
    claim_alert_slot,
    close_incident_on_commit,
    first_check_at,
    follow_logs_alert,
    has_any_filter,
    logs_state_of_platform,
    next_allowed_check_at,
    platform_check_rows,
)
from products.logs.backend.facade.platform_ownership import delete_alert, on_created, on_updated
from products.logs.backend.models import MAX_EVALUATION_PERIODS, LogsAlertConfiguration, LogsAlertEvent

MAX_SIMULATE_LOOKBACK_DAYS = 30
MAX_SIMULATE_BUCKETS = 15_000
MAX_DESTINATION_IDS_PER_DELETE_REQUEST = 100


class LogsAlertListQuerySerializer(serializers.Serializer):
    created_by = serializers.UUIDField(
        required=False,
        help_text="Only return log alerts created by the user with this UUID.",
    )


STATE_TIMELINE_LOOKBACK_HOURS = 24
# Mirrors LogsAlertConfiguration.check_interval_minutes' default — used as the
# simulate endpoint's default cadence so it matches production when callers
# don't override it.
DEFAULT_CHECK_INTERVAL_MINUTES = 5
_SENTINEL: Final = object()
_NOT_ANNOTATED: Final = object()
_SINGLE_INSTANCE: Final = Grouping()


def _any_field_changed(instance: LogsAlertConfiguration, validated_data: dict, fields: set[str]) -> bool:
    return any(f in validated_data and validated_data[f] != getattr(instance, f) for f in fields)


class LogsAlertStateIntervalSerializer(serializers.Serializer):
    start = serializers.DateTimeField(help_text="Interval start (UTC, inclusive).")
    end = serializers.DateTimeField(help_text="Interval end (UTC, exclusive).")
    state = serializers.ChoiceField(
        choices=LogsAlertConfiguration.State.choices,
        help_text="Alert state during this interval.",
    )
    enabled = serializers.BooleanField(
        help_text="Whether the alert was enabled during this interval. Disabled alerts keep their state but are inactive.",
    )


class StateInterval(TypedDict):
    start: datetime
    end: datetime
    state: str
    enabled: bool


def _state_timeline_window_bounds() -> tuple[datetime, datetime]:
    # Pixel-precise window — no hour quantization, since the frontend maps each event
    # timestamp to an x-coordinate directly.
    end = datetime.now(UTC)
    return end - dt.timedelta(hours=STATE_TIMELINE_LOOKBACK_HOURS), end


@extend_schema_field(LogsAlertFilters)  # type: ignore[arg-type]
class LogsAlertFiltersField(serializers.JSONField):
    """JSONField typed against the `LogsAlertFilters` Pydantic schema.

    Annotating with `@extend_schema_field(LogsAlertFilters)` is what makes the
    generated OpenAPI spec — and downstream MCP zod schemas — surface the actual
    shape (severityLevels / serviceNames / filterGroup) to API consumers and AI
    agents, instead of an opaque `JSONField` blob. Validating with
    `model_validate` on write rejects shape errors at the API boundary so the
    alerting worker never sees a structurally invalid `filterGroup`.
    """

    def to_internal_value(self, data: dict | list) -> dict:
        value = super().to_internal_value(data)
        if not isinstance(value, dict):
            raise serializers.ValidationError("Must be a JSON object.")
        try:
            LogsAlertFilters.model_validate(value)
        except PydanticValidationError as e:
            first = e.errors()[0]
            location = ".".join(str(p) for p in first["loc"]) or "filters"
            raise serializers.ValidationError(f"Invalid filters shape at `{location}`: {first['msg']}") from e
        return value


class LogsAlertDestinationResponseSerializer(serializers.Serializer):
    hog_function_ids = serializers.ListField(child=serializers.UUIDField())


class LogsAlertDestinationConfigSerializer(LogsAlertDestinationResponseSerializer):
    type = serializers.ChoiceField(choices=LOGS_DESTINATION_TYPES, help_text="Notification destination type.")
    enabled = serializers.BooleanField(
        help_text=(
            "Whether every HogFunction in the group is enabled, so the destination notifies for all "
            "alert event kinds. This is the stored setting: a destination PostHog stopped delivering "
            "to after repeated failures still reads as true."
        )
    )
    message_customized = serializers.BooleanField(
        help_text=(
            "Whether any HogFunction in the group sends something other than the stock message, "
            "such as an edited body, headers, method or code. A customized destination sends exactly "
            "what its HogFunctions build."
        )
    )
    slack_workspace_id = serializers.IntegerField(required=False)
    slack_channel_id = serializers.CharField(required=False)
    webhook_url = serializers.CharField(
        required=False,
        help_text="Webhook endpoint reduced to scheme and host. The path, query and userinfo carry the secret.",
    )
    pagerduty_routing_key = serializers.CharField(
        required=False,
        help_text="PagerDuty integration key reduced to its last four characters.",
    )
    pagerduty_severity = serializers.ChoiceField(
        choices=[choice.value for choice in PagerDutySeverity],
        required=False,
        help_text="Severity of the PagerDuty incident.",
    )
    pagerduty_region = serializers.ChoiceField(
        choices=[choice.value for choice in PagerDutyRegion],
        required=False,
        help_text="PagerDuty service region the events go to.",
    )


_PLATFORM_RUNTIME_CONTEXT_KEY: Final = "platform_runtime"
_PLATFORM_HISTORY_CONTEXT_KEY: Final = "platform_history"


def _platform_runtime_of(alerts: list[LogsAlertConfiguration]) -> dict[UUID, PlatformAlertRuntime]:
    owned = [alert for alert in alerts if alert.platform_owned]
    if not owned:
        return {}
    return runtime_by_legacy_id(team_id=owned[0].team_id, legacy_configuration_ids=[alert.id for alert in owned])


def _platform_history_of(
    alerts: list[LogsAlertConfiguration], window: tuple[datetime, datetime]
) -> dict[UUID, PlatformAlertHistory] | None:
    """None when ClickHouse fails. The logs row then stands in, because a stale timeline is a
    better answer than a failed list."""
    owned = [alert for alert in alerts if alert.platform_owned]
    if not owned:
        return {}
    try:
        return history_by_legacy_id(
            team_id=owned[0].team_id,
            legacy_configuration_ids=[alert.id for alert in owned],
            since=window[0],
            until=window[1],
        )
    except Exception as error:
        capture_exception(error)
        return None


class LogsAlertConfigurationListSerializer(serializers.ListSerializer):
    def to_representation(self, data: Any) -> list[dict[str, Any]]:
        alerts = list(data.all() if isinstance(data, Manager) else data)
        # One platform read of each kind for the page, which the child serializer finds in the
        # shared context.
        self.context[_PLATFORM_RUNTIME_CONTEXT_KEY] = _platform_runtime_of(alerts)
        self.context[_PLATFORM_HISTORY_CONTEXT_KEY] = _platform_history_of(
            alerts, self.context.get("state_timeline_window") or _state_timeline_window_bounds()
        )
        return super().to_representation(alerts)


# Kinds of the boundaries a moved alert's timeline adds to the logs event kinds.
_PLATFORM_CHANGE: Final = "platform_change"
_SNOOZE_EXPIRY: Final = "snooze_expiry"
_SNOOZE_KINDS: Final = (LogsAlertEvent.Kind.SNOOZE, LogsAlertEvent.Kind.UNSNOOZE)
_PLATFORM_TIMELINE_LOGS_KINDS: Final = (
    LogsAlertEvent.Kind.ENABLE,
    LogsAlertEvent.Kind.DISABLE,
    LogsAlertEvent.Kind.RESET,
    *_SNOOZE_KINDS,
)


@frozen
class _TimelineEvent:
    """A boundary of a moved alert's timeline, in the shape the timeline walk reads."""

    kind: str
    created_at: datetime
    state_before: str
    state_after: str


class LogsAlertGroupingSerializer(GroupingSerializer):
    """How a logs alert splits its results into instances."""

    # The logs row has no grouping column. Every alert reads as single here, and `to_representation`
    # of the alert serializer replaces it with the platform copy's grouping for an alert the platform owns.
    def get_attribute(self, instance: LogsAlertConfiguration) -> Grouping:
        return _SINGLE_INSTANCE


class LogsAlertConfigurationSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(
        read_only=True,
        help_text="Unique identifier for this alert.",
    )
    name = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="Human-readable name for this alert. Defaults to 'Untitled alert' on create when omitted.",
    )
    enabled = serializers.BooleanField(
        default=True,
        help_text="Whether the alert is actively being evaluated. Disabling resets the state to not_firing.",
    )
    filters = LogsAlertFiltersField(
        required=False,
        help_text="Filter criteria — subset of LogsViewerFilters. Must contain at least one of: "
        "severityLevels (list of severity strings), serviceNames (list of service name strings), "
        "or filterGroup (property filter group object). May be empty on draft alerts (enabled=false).",
    )
    threshold_count = serializers.IntegerField(
        min_value=0,
        default=100,
        help_text="Number of matching log entries that constitutes a threshold breach within the evaluation window. Defaults to 100. Use 0 with the 'above' operator to fire on any matching log.",
    )
    first_enabled_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the alert was first enabled. Null means the alert is still in draft state.",
    )
    threshold_operator = serializers.ChoiceField(
        choices=LogsAlertConfiguration.ThresholdOperator.choices,
        default=LogsAlertConfiguration.ThresholdOperator.ABOVE,
        help_text="Whether the alert fires when the count is above or below the threshold.",
    )
    window_minutes = serializers.IntegerField(
        default=5,
        help_text="Time window in minutes over which log entries are counted. Allowed values: 5, 10, 15, 30, 60.",
    )
    check_interval_minutes = serializers.IntegerField(
        read_only=True,
        help_text="How often the alert is evaluated, in minutes. Server-managed.",
    )
    state = serializers.ChoiceField(
        choices=LogsAlertConfiguration.State.choices,
        read_only=True,
        help_text="Current alert state: not_firing, firing, pending_resolve, errored, or snoozed. Server-managed.",
    )
    evaluation_periods = serializers.IntegerField(
        default=1,
        min_value=1,
        max_value=MAX_EVALUATION_PERIODS,
        help_text="Total number of check periods in the sliding evaluation window for firing (M in N-of-M).",
    )
    datapoints_to_alarm = serializers.IntegerField(
        default=1,
        min_value=1,
        max_value=MAX_EVALUATION_PERIODS,
        help_text="How many periods within the evaluation window must breach the threshold to fire (N in N-of-M).",
    )
    cooldown_minutes = serializers.IntegerField(
        default=0,
        min_value=0,
        help_text=(
            "Minimum minutes between notifications. The alert notifies once when it starts firing and once "
            "when it resolves. It does not notify again on each check while it stays firing. A fire or resolve "
            "notification inside the cooldown is skipped. Cooldown does not apply to PagerDuty incidents. "
            "0 means no minimum."
        ),
    )
    schedule_restriction = ScheduleRestrictionField(
        required=False,
        allow_null=True,
        help_text="Blocked local time windows when the alert must not run. Times use the project timezone. Null disables quiet hours.",
    )
    snooze_until = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="ISO 8601 timestamp until which the alert is snoozed. Set to null to unsnooze.",
    )
    next_check_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the next evaluation is scheduled. Server-managed.",
    )
    last_notified_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the last notification was sent. Server-managed.",
    )
    last_checked_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the alert was last evaluated. Server-managed.",
    )
    consecutive_failures = serializers.IntegerField(
        read_only=True,
        help_text="Number of consecutive evaluation failures. Resets on success. Server-managed.",
    )
    last_error_message = serializers.SerializerMethodField(
        help_text=(
            "Error message from the most recent errored check, or null if the alert's "
            "most recent check was successful. Sourced from LogsAlertEvent without "
            "denormalization so retention-aware cleanup rules stay the only source of truth. "
            "For an alert the alerts platform evaluates, sourced from the platform's check history."
        ),
    )
    created_at = serializers.DateTimeField(
        read_only=True,
        help_text="When the alert was created.",
    )
    created_by = UserBasicSerializer(read_only=True)
    updated_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the alert was last modified.",
    )
    state_timeline = serializers.SerializerMethodField(
        help_text=(
            f"Continuous state intervals over the last {STATE_TIMELINE_LOOKBACK_HOURS}h, ordered oldest-first. "
            "Each interval covers a span during which (state, enabled) was constant. Derived from "
            "LogsAlertEvent rows walked in chronological order; consecutive identical intervals are "
            "collapsed. For an alert the alerts platform evaluates, state changes come from the "
            "platform's check history instead. Drives the 'Last 24h' status bar on the alert list."
        ),
    )
    destination_types = serializers.SerializerMethodField(
        help_text=(
            "Notification destination types configured for this alert — e.g. 'slack', 'webhook'. "
            "Empty list means no notifications will fire. One or more destinations should be added "
            "after creating an alert."
        ),
    )
    grouping = LogsAlertGroupingSerializer(
        required=False,
        help_text=(
            "How the alert splits its results into instances. Mode single keeps one instance for the whole "
            "alert. Mode by_result_labels with keys service_name and/or severity_text keeps one instance per "
            "service or severity, each firing and resolving on its own, and needs threshold_operator above. "
            "Only an alert the alerts platform evaluates can group. Any other alert reads as single and "
            "rejects a different value. Omit it on update to keep the current grouping. Changing the keys "
            "deletes the existing instances and closes their notification threads without a message."
        ),
    )
    platform_owned = serializers.BooleanField(
        read_only=True,
        help_text=(
            "Whether the alerts platform evaluates this alert and sends its notifications. Only such an "
            "alert can set a grouping other than single."
        ),
    )

    @extend_schema_field(LogsAlertStateIntervalSerializer(many=True))
    def get_state_timeline(self, obj: LogsAlertConfiguration) -> list[StateInterval]:
        window = self.context.get("state_timeline_window") or _state_timeline_window_bounds()
        return self._state_intervals(obj, self._timeline_events(obj, window[0]), obj.state, window)

    def _timeline_events(self, obj: LogsAlertConfiguration, window_start: datetime) -> list[LogsAlertEvent]:
        # Events are prefetched as `_state_timeline_events` on the list endpoint; fall
        # back to a direct query for callers that build this serializer outside the viewset
        # (admin, tests).
        events = getattr(obj, "_state_timeline_events", None)
        if events is None:
            events = list(
                LogsAlertEvent.objects.filter(alert=obj, created_at__gte=window_start)
                .order_by("created_at")
                .only("kind", "created_at", "state_before", "state_after")
            )
        return events

    def _platform_state_timeline(
        self,
        obj: LogsAlertConfiguration,
        history: PlatformAlertHistory | None,
        platform_state: PlatformAlertState,
        window: tuple[datetime, datetime],
    ) -> list[StateInterval]:
        """The timeline of an alert the platform owns.

        The platform's history holds the state changes. The logs API still writes the toggles, the
        snoozes and the resets, so they come from LogsAlertEvent. A reset writes no platform history,
        so its logs row is the only record that the platform state went back to not firing. Logs
        check rows are left out, because the logs stack only shadows an alert the platform owns.

        Each logs event keeps its own time, and the state shown at any moment is snoozed while a
        snooze holds, else the platform's state. A snooze that expired leaves no event, so only
        the current snooze's `snooze_until` can end one inside the window.
        """
        window_start, window_end = window
        logs_events = [
            event for event in self._timeline_events(obj, window_start) if event.kind in _PLATFORM_TIMELINE_LOGS_KINDS
        ]
        snooze_events = [event for event in logs_events if event.kind in _SNOOZE_KINDS]

        # Each boundary is (time, kind, the platform state it moves to or None).
        boundaries: list[tuple[datetime, str, PlatformAlertState | None]] = [
            (change.occurred_at, _PLATFORM_CHANGE, change.state)
            for change in (history.state_changes if history is not None else ())
        ]
        boundaries.extend((event.created_at, event.kind, None) for event in logs_events)
        snooze_until = obj.snooze_until
        if (
            snooze_until is not None
            and window_start < snooze_until < window_end
            and not any(event.created_at >= snooze_until for event in snooze_events)
        ):
            boundaries.append((snooze_until, _SNOOZE_EXPIRY, None))
        boundaries.sort(key=lambda boundary: boundary[0])

        if history is not None and history.state_changes:
            platform_state = history.state_changes[0].previous_state
        if snooze_events:
            snoozed = snooze_events[0].kind == LogsAlertEvent.Kind.UNSNOOZE
        else:
            snoozed = (
                obj.state == LogsAlertConfiguration.State.SNOOZED
                and snooze_until is not None
                and snooze_until > window_start
            )

        def shown() -> str:
            if snoozed:
                return LogsAlertConfiguration.State.SNOOZED
            return logs_state_of_platform(
                platform_state, logs_state=obj.state, snooze_until=None, at=window_start
            ).value

        events: list[_TimelineEvent] = []
        for at, kind, moved_to in boundaries:
            before = shown()
            if moved_to is not None:
                platform_state = moved_to
            elif kind == LogsAlertEvent.Kind.RESET:
                platform_state = PlatformAlertState.NOT_FIRING
            elif kind == LogsAlertEvent.Kind.SNOOZE:
                snoozed = True
            elif kind in (LogsAlertEvent.Kind.UNSNOOZE, _SNOOZE_EXPIRY):
                snoozed = False
            events.append(_TimelineEvent(kind=kind, created_at=at, state_before=before, state_after=shown()))
        return self._state_intervals(obj, events, shown(), window)

    def _state_intervals(
        self,
        obj: LogsAlertConfiguration,
        events: Sequence[LogsAlertEvent | _TimelineEvent],
        fallback_state: str,
        window: tuple[datetime, datetime],
    ) -> list[StateInterval]:
        window_start, window_end = window

        # Seed state at window_start: the first in-window event tells us what state was
        # active just before it fired. Fallback to the alert's current state when there are
        # no events at all in the window.
        seed_state = events[0].state_before if events else fallback_state

        # Seed enabled at window_start: prefer the latest ENABLE/DISABLE at-or-before
        # window_start (annotated on the queryset), then infer from the first in-window
        # toggle (opposite kind), else fall back to alert.enabled (constant if never toggled).
        pre_window_toggle = getattr(obj, "_pre_window_toggle_kind", _NOT_ANNOTATED)
        if pre_window_toggle is _NOT_ANNOTATED:
            pre_window_toggle = (
                LogsAlertEvent.objects.filter(
                    alert=obj,
                    kind__in=(LogsAlertEvent.Kind.ENABLE, LogsAlertEvent.Kind.DISABLE),
                    created_at__lt=window_start,
                )
                .order_by("-created_at")
                .values_list("kind", flat=True)
                .first()
            )
        if pre_window_toggle is not None:
            seed_enabled = pre_window_toggle == LogsAlertEvent.Kind.ENABLE
        else:
            first_in_window_toggle = next(
                (e for e in events if e.kind in (LogsAlertEvent.Kind.ENABLE, LogsAlertEvent.Kind.DISABLE)),
                None,
            )
            if first_in_window_toggle is not None:
                # Before a toggle fired, enabled was the opposite of what the toggle set it to.
                seed_enabled = first_in_window_toggle.kind == LogsAlertEvent.Kind.DISABLE
            else:
                seed_enabled = obj.enabled

        intervals: list[StateInterval] = []
        current_start = window_start
        current_state = seed_state
        current_enabled = seed_enabled

        for event in events:
            if event.kind == LogsAlertEvent.Kind.ENABLE:
                new_enabled, new_state = True, event.state_after
            elif event.kind == LogsAlertEvent.Kind.DISABLE:
                new_enabled, new_state = False, event.state_after
            else:
                new_enabled, new_state = current_enabled, event.state_after

            if new_state == current_state and new_enabled == current_enabled:
                continue

            intervals.append(
                {
                    "start": current_start,
                    "end": event.created_at,
                    "state": current_state,
                    "enabled": current_enabled,
                }
            )
            current_start = event.created_at
            current_state = new_state
            current_enabled = new_enabled

        intervals.append(
            {
                "start": current_start,
                "end": window_end,
                "state": current_state,
                "enabled": current_enabled,
            }
        )
        return intervals

    @extend_schema_field(serializers.ListField(child=serializers.ChoiceField(choices=LOGS_DESTINATION_TYPES)))
    def get_destination_types(self, obj: LogsAlertConfiguration) -> list[str]:
        # N+1 is acceptable: max 20 alerts per team, each query a fast indexed lookup.
        configured_template_ids = configured_destination_template_ids(
            team_id=obj.team_id,
            alert_id=str(obj.id),
            allowed_event_ids=LOGS_ALERT_EVENT_IDS,
        )
        return sorted(
            destination_type.value
            for destination_type in LOGS_DESTINATION_TYPES
            if destination_template_id(destination_type) in configured_template_ids
        )

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_last_error_message(self, obj: LogsAlertConfiguration) -> str | None:
        # The viewset annotates `_latest_error_message` via Subquery to avoid N+1 on list.
        # Fallback direct query covers callers that construct this serializer outside the
        # viewset (tests, admin actions).
        annotated = getattr(obj, "_latest_error_message", _NOT_ANNOTATED)
        if annotated is not _NOT_ANNOTATED:
            # Subquery annotation yields either the error_message string or None.
            return cast(str | None, annotated)
        return (
            LogsAlertEvent.objects.filter(
                alert=obj,
                kind=LogsAlertEvent.Kind.CHECK,
                error_message__isnull=False,
            )
            .order_by("-created_at")
            .values_list("error_message", flat=True)
            .first()
        )

    def to_representation(self, instance: LogsAlertConfiguration) -> dict[str, Any]:
        data = super().to_representation(instance)
        if not instance.platform_owned:
            return data
        # The platform evaluates an alert it owns, so the logs row stops moving once the shadow ends.
        runtimes = self.context.get(_PLATFORM_RUNTIME_CONTEXT_KEY)
        if runtimes is None:
            runtimes = _platform_runtime_of([instance])
        runtime = runtimes.get(instance.id)
        if runtime is None:
            return data
        data["state"] = logs_state_of_platform(
            runtime.state, logs_state=instance.state, snooze_until=instance.snooze_until, at=timezone.now()
        ).value
        data["consecutive_failures"] = runtime.consecutive_failures
        data["grouping"] = self.fields["grouping"].to_representation(runtime.grouping)
        data["next_check_at"] = self.fields["next_check_at"].to_representation(runtime.next_check_at)
        data["last_notified_at"] = self.fields["last_notified_at"].to_representation(runtime.last_notified_at)

        histories = self.context.get(_PLATFORM_HISTORY_CONTEXT_KEY, _NOT_ANNOTATED)
        window = self.context.get("state_timeline_window") or _state_timeline_window_bounds()
        if histories is _NOT_ANNOTATED:
            histories = _platform_history_of([instance], window)
        if histories is None:
            return data
        history = cast(dict[UUID, PlatformAlertHistory], histories).get(instance.id)
        data["state_timeline"] = self._platform_state_timeline(instance, history, runtime.state, window)
        # With no platform check in the window, the logs row is the newest check anyone made.
        if history is not None:
            data["last_checked_at"] = self.fields["last_checked_at"].to_representation(history.last_checked_at)
            data["last_error_message"] = history.last_error_message
        return data

    class Meta:
        model = LogsAlertConfiguration
        list_serializer_class = LogsAlertConfigurationListSerializer
        fields = [
            "id",
            "name",
            "enabled",
            "filters",
            "threshold_count",
            "threshold_operator",
            "window_minutes",
            "check_interval_minutes",
            "state",
            "evaluation_periods",
            "datapoints_to_alarm",
            "cooldown_minutes",
            "schedule_restriction",
            "snooze_until",
            "next_check_at",
            "last_notified_at",
            "last_checked_at",
            "consecutive_failures",
            "last_error_message",
            "state_timeline",
            "destination_types",
            "grouping",
            "platform_owned",
            "first_enabled_at",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "check_interval_minutes",
            "state",
            "next_check_at",
            "last_notified_at",
            "last_checked_at",
            "consecutive_failures",
            "last_error_message",
            "state_timeline",
            "destination_types",
            "platform_owned",
            "first_enabled_at",
            "created_at",
            "created_by",
            "updated_at",
        ]

    def validate(self, attrs: dict) -> dict:
        filters = attrs.get("filters", getattr(self.instance, "filters", None) or {})

        if self.instance is not None:
            effective_enabled = attrs.get("enabled", self.instance.enabled)
        else:
            effective_enabled = attrs.get("enabled", True)

        # Drafts (enabled=false, no filters) are allowed; otherwise filter shape is required.
        if effective_enabled or filters:
            _validate_filters(filters)

        window = attrs.get("window_minutes", getattr(self.instance, "window_minutes", None))
        if window is not None and window not in ALLOWED_WINDOW_MINUTES:
            raise ValidationError({"window_minutes": f"Must be one of {sorted(ALLOWED_WINDOW_MINUTES)}."})

        evaluation_periods = attrs.get("evaluation_periods", getattr(self.instance, "evaluation_periods", 1))
        datapoints_to_alarm = attrs.get("datapoints_to_alarm", getattr(self.instance, "datapoints_to_alarm", 1))
        if datapoints_to_alarm > evaluation_periods:
            raise ValidationError(
                {
                    "datapoints_to_alarm": f"Cannot exceed evaluation_periods ({datapoints_to_alarm} > {evaluation_periods})."
                }
            )

        snooze_until = attrs.get("snooze_until")
        if snooze_until is not None and snooze_until <= datetime.now(UTC):
            raise ValidationError({"snooze_until": "Must be a future datetime."})

        if "schedule_restriction" in attrs:
            try:
                attrs["schedule_restriction"] = validate_and_normalize_schedule_restriction(
                    attrs["schedule_restriction"]
                )
            except ValueError as e:
                raise ValidationError({"schedule_restriction": str(e)}) from e

        return attrs

    def update(self, instance: LogsAlertConfiguration, validated_data: dict) -> LogsAlertConfiguration:
        if "name" in validated_data and not validated_data.get("name", "").strip():
            validated_data["name"] = "Untitled alert"

        snooze_data = validated_data.pop("snooze_until", _SENTINEL)
        grouping: Grouping | None = validated_data.pop("grouping", None)

        threshold_or_filter_fields = {
            "threshold_count",
            "threshold_operator",
            "filters",
            "datapoints_to_alarm",
            "evaluation_periods",
        }

        threshold_changed = _any_field_changed(instance, validated_data, threshold_or_filter_fields)
        window_changed = _any_field_changed(instance, validated_data, {"window_minutes"})
        schedule_restriction_changed = _any_field_changed(instance, validated_data, {"schedule_restriction"})

        enabled_change: bool | None = None
        if "enabled" in validated_data and validated_data["enabled"] != instance.enabled:
            enabled_change = validated_data["enabled"]

        # Wrap the state-machine transition + LogsAlertEvent insert + super().save in one
        # transaction so a save failure can't orphan an audit row (or vice versa). Matches
        # the atomic guarantee the reset viewset action already provides.
        with transaction.atomic():
            # Resolve the state-machine transition in priority order: enable/disable wins over
            # snooze, which wins over threshold/filter changes. Window-only edits don't touch
            # state at all. All transitions return an Outcome; apply_outcome is the single
            # place that actually writes to `state`/`consecutive_failures`.
            snapshot = instance.to_snapshot()
            state_before = instance.state
            close_reason: IncidentCloseReason | None = None
            if enabled_change is True:
                if instance.first_enabled_at is None:
                    instance.first_enabled_at = timezone.now()
                    if "first_enabled_at" not in validated_data:
                        validated_data["first_enabled_at"] = instance.first_enabled_at
                apply_outcome(instance, apply_enable(snapshot), kind=LogsAlertEvent.Kind.ENABLE)
            elif enabled_change is False:
                apply_outcome(instance, apply_disable(snapshot), kind=LogsAlertEvent.Kind.DISABLE)
                close_reason = IncidentCloseReason.DISABLED
            elif snooze_data is not _SENTINEL:
                if snooze_data is None:
                    apply_outcome(instance, apply_unsnooze(snapshot), kind=LogsAlertEvent.Kind.UNSNOOZE)
                else:
                    apply_outcome(instance, apply_snooze(snapshot), kind=LogsAlertEvent.Kind.SNOOZE)
                    close_reason = IncidentCloseReason.SNOOZED
            elif threshold_changed:
                apply_outcome(instance, apply_threshold_change(snapshot), kind=LogsAlertEvent.Kind.THRESHOLD_CHANGE)
                close_reason = IncidentCloseReason.CONFIG_CHANGED
            # The edge check inside decides whether a close goes out, so a new branch above that forgets
            # its reason still closes the incident.
            close_incident_on_commit(
                team_id=instance.team_id,
                alert_id=str(instance.id),
                state_before=state_before,
                state_after=instance.state,
                reason=close_reason or IncidentCloseReason.CONFIG_CHANGED,
            )

            # snooze_until is a timestamp column, not a state — carry it alongside the state
            # transition so the serializer's single save persists both.
            if snooze_data is not _SENTINEL:
                instance.snooze_until = snooze_data

            if (
                threshold_changed
                or window_changed
                or schedule_restriction_changed
                or (enabled_change is True and instance.schedule_restriction)
            ):
                next_schedule_restriction = validated_data.get("schedule_restriction", instance.schedule_restriction)
                if next_schedule_restriction:
                    validated_data["next_check_at"] = next_allowed_check_at(
                        datetime.now(UTC),
                        team_timezone=instance.team.timezone,
                        schedule_restriction=next_schedule_restriction,
                    )
                else:
                    instance.clear_next_check()

            updated = super().update(instance, validated_data)
            _write_platform_edit(
                lambda: on_updated(
                    team_id=updated.team_id,
                    alert_id=updated.id,
                    snooze_changed=snooze_data is not _SENTINEL,
                    grouping=grouping,
                )
            )
            if not updated.platform_owned and enabled_change is True:
                transaction.on_commit(
                    lambda: follow_logs_alert(team_id=updated.team_id, alert_id=updated.id), robust=True
                )
            return updated

    def create(self, validated_data: dict) -> LogsAlertConfiguration:
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user

        if not validated_data.get("name", "").strip():
            validated_data["name"] = "Untitled alert"

        if validated_data.get("enabled", True):
            validated_data["first_enabled_at"] = timezone.now()
        grouping: Grouping | None = validated_data.pop("grouping", None)

        with transaction.atomic():
            try:
                claim_alert_slot(validated_data["team_id"])
            except AlertLimitReached as error:
                raise ValidationError(str(error)) from error
            if schedule_restriction := validated_data.get("schedule_restriction"):
                validated_data["next_check_at"] = first_check_at(validated_data["team_id"], schedule_restriction)
            created = super().create(validated_data)
            # Raised inside the transaction, so a grouping the alert cannot take leaves no alert behind.
            if _write_platform_edit(
                lambda: on_created(team_id=created.team_id, alert_id=created.id, at=timezone.now(), grouping=grouping)
            ):
                created.refresh_from_db(fields=["owner", "owner_changed_at"])
            elif created.enabled:
                transaction.on_commit(
                    lambda: follow_logs_alert(team_id=created.team_id, alert_id=created.id), robust=True
                )
            return created


def _write_platform_edit[T](write: Callable[[], T]) -> T:
    try:
        return write()
    except InvalidPlatformAlertEdit as error:
        raise ValidationError({error.field_name: str(error)}) from error


def _validate_filters(filters: dict) -> None:
    """Cross-field requirement that at least one filter is present.

    Per-field shape validation is handled by `LogsAlertFiltersField`, which runs
    `LogsAlertFilters.model_validate` on the raw input — by the time this helper
    runs, `filters` is a structurally valid `LogsAlertFilters` dict.
    """
    if not isinstance(filters, dict):
        raise ValidationError({"filters": "Must be a JSON object."})
    if not has_any_filter(filters):
        raise ValidationError(
            {"filters": "At least one filter is required (severityLevels, serviceNames, or filterGroup)."}
        )


class LogsAlertConfigurationDetailSerializer(LogsAlertConfigurationSerializer):
    """One alert, with the destinations attached to it. The list endpoint leaves them out:
    reading a destination pulls its stored inputs, which run to several KB per row."""

    destinations = serializers.SerializerMethodField(
        help_text=(
            "This alert's notification destinations, one entry per destination. Each carries the "
            "HogFunction IDs that delete it as a group, and its configuration with credential-bearing "
            "URL components removed."
        ),
    )

    class Meta(LogsAlertConfigurationSerializer.Meta):
        fields = [*LogsAlertConfigurationSerializer.Meta.fields, "destinations"]
        read_only_fields = [*LogsAlertConfigurationSerializer.Meta.read_only_fields, "destinations"]

    @extend_schema_field(LogsAlertDestinationConfigSerializer(many=True))
    def get_destinations(self, obj: LogsAlertConfiguration) -> list[dict[str, Any]]:
        groups = list_alert_destination_groups(
            team_id=obj.team_id,
            alert_id=str(obj.id),
            allowed_event_ids=LOGS_ALERT_EVENT_IDS,
        )
        customized = customized_alert_destination_ids(
            team_id=obj.team_id, alert_id=str(obj.id), allowed_event_ids=LOGS_ALERT_EVENT_IDS
        )
        return [
            {
                "hog_function_ids": list(group.hog_function_ids),
                "enabled": group.fully_enabled,
                "message_customized": not customized.isdisjoint(group.hog_function_ids),
                **redact_destination_data(group.data),
            }
            for group in groups
        ]


class LogsAlertEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = LogsAlertEvent
        fields = [
            "id",
            "created_at",
            "kind",
            "state_before",
            "state_after",
            "threshold_breached",
            "result_count",
            "error_message",
            "query_duration_ms",
        ]
        read_only_fields = fields


class LogsAlertSimulateBucketSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField(help_text="Bucket start timestamp.")
    count = serializers.IntegerField(help_text="Number of matching logs in this bucket.")
    threshold_breached = serializers.BooleanField(help_text="Whether the count crossed the threshold in this bucket.")
    state = serializers.CharField(help_text="Alert state after evaluating this bucket.")
    notification = serializers.CharField(help_text="Notification action: none, fire, or resolve.")
    reason = serializers.CharField(help_text="Human-readable explanation of the state transition.")


class LogsAlertSimulateRequestSerializer(serializers.Serializer):
    filters = LogsAlertFiltersField(help_text="Filter criteria — same format as LogsAlertConfiguration.filters.")
    threshold_count = serializers.IntegerField(
        min_value=0,
        help_text="Threshold count to evaluate against.",
    )
    threshold_operator = serializers.ChoiceField(
        choices=LogsAlertConfiguration.ThresholdOperator.choices,
        help_text="Whether the alert fires when the count is above or below the threshold.",
    )
    window_minutes = serializers.IntegerField(
        help_text="Window size in minutes — determines bucket interval.",
    )
    check_interval_minutes = serializers.IntegerField(
        default=DEFAULT_CHECK_INTERVAL_MINUTES,
        min_value=1,
        max_value=max(ALLOWED_WINDOW_MINUTES),
        help_text="How often the alert is evaluated, in minutes.",
    )
    evaluation_periods = serializers.IntegerField(
        default=1,
        min_value=1,
        max_value=MAX_EVALUATION_PERIODS,
        help_text="Total check periods in the N-of-M evaluation window (M).",
    )
    datapoints_to_alarm = serializers.IntegerField(
        default=1,
        min_value=1,
        max_value=MAX_EVALUATION_PERIODS,
        help_text="How many periods must breach to fire (N in N-of-M).",
    )
    cooldown_minutes = serializers.IntegerField(
        default=0,
        min_value=0,
        help_text="Minimum minutes between notifications. A fire or resolve notification inside the cooldown is skipped. 0 means no minimum.",
    )
    date_from = serializers.CharField(
        help_text="Relative date string for how far back to simulate (e.g. '-24h', '-7d', '-30d').",
    )

    def validate_filters(self, value: dict) -> dict:
        _validate_filters(value)
        return value

    def validate_date_from(self, value: str) -> str:
        try:
            parsed = relative_date_parse(value, ZoneInfo("UTC"))
        except Exception:
            raise ValidationError("Invalid date_from value.")
        min_allowed = datetime.now(UTC) - dt.timedelta(days=MAX_SIMULATE_LOOKBACK_DAYS)
        if parsed < min_allowed:
            raise ValidationError(f"date_from cannot be more than {MAX_SIMULATE_LOOKBACK_DAYS} days in the past.")
        return value

    def validate_window_minutes(self, value: int) -> int:
        if value not in ALLOWED_WINDOW_MINUTES:
            raise ValidationError(f"Must be one of {sorted(ALLOWED_WINDOW_MINUTES)}.")
        return value

    def validate(self, attrs: dict) -> dict:
        if attrs.get("datapoints_to_alarm", 1) > attrs.get("evaluation_periods", 1):
            raise ValidationError({"datapoints_to_alarm": "Cannot exceed evaluation_periods."})
        if attrs["check_interval_minutes"] > attrs["window_minutes"]:
            raise ValidationError({"check_interval_minutes": "Cannot exceed window_minutes."})
        return attrs


class LogsAlertSimulateResponseSerializer(serializers.Serializer):
    buckets = LogsAlertSimulateBucketSerializer(
        many=True, help_text="Time-bucketed counts with full state machine evaluation."
    )
    fire_count = serializers.IntegerField(help_text="Number of times the alert would have sent a fire notification.")
    resolve_count = serializers.IntegerField(
        help_text="Number of times the alert would have sent a resolve notification."
    )
    total_buckets = serializers.IntegerField(help_text="Total number of buckets in the simulation window.")
    threshold_count = serializers.IntegerField(help_text="Threshold count used for evaluation.")
    threshold_operator = serializers.CharField(help_text="Threshold operator used for evaluation.")


class LogsAlertCreateDestinationSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=LOGS_DESTINATION_TYPES, help_text="Notification destination type.")
    slack_workspace_id = serializers.IntegerField(
        required=False, help_text="Integration ID for the Slack workspace. Required when type=slack."
    )
    slack_channel_id = serializers.CharField(required=False, help_text="Slack channel ID. Required when type=slack.")
    slack_channel_name = serializers.CharField(
        required=False, allow_blank=True, help_text="Human-readable channel name for display."
    )
    webhook_url = serializers.URLField(
        required=False,
        help_text="HTTPS endpoint to post to. Required for webhook and teams.",
    )
    pagerduty_routing_key = serializers.CharField(
        required=False,
        trim_whitespace=True,
        help_text="Integration key of a PagerDuty Events API v2 integration. Required when type=pagerduty.",
    )
    pagerduty_severity = serializers.ChoiceField(
        choices=[choice.value for choice in PagerDutySeverity],
        required=False,
        default=PagerDutySeverity.CRITICAL.value,
        help_text="Severity PagerDuty records on the incident. Used when type=pagerduty.",
    )
    pagerduty_region = serializers.ChoiceField(
        choices=[choice.value for choice in PagerDutyRegion],
        required=False,
        default=PagerDutyRegion.US.value,
        help_text="PagerDuty service region of the account. Used when type=pagerduty.",
    )

    def validate(self, attrs: dict) -> dict:
        data = cast(AlertDestinationData, attrs)
        data["type"] = DestinationType(attrs["type"])
        try:
            validate_destination_data(data, allowed_destination_types=LOGS_DESTINATION_TYPES)
        except AlertDestinationValidationError as error:
            if error.field:
                raise ValidationError({error.field: error.message})
            raise ValidationError(error.message)
        return attrs


class LogsAlertDeleteDestinationSerializer(serializers.Serializer):
    hog_function_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        help_text="HogFunction IDs to delete as one atomic destination group.",
    )


MAX_DESTINATION_SENDS: Final = 20


class LogsAlertDestinationSendsQuerySerializer(serializers.Serializer):
    hog_function_ids = RepeatedOrCommaSeparatedListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=MAX_DESTINATION_IDS_PER_DELETE_REQUEST,
        help_text="HogFunction IDs of one destination group. IDs that are not this alert's are ignored.",
    )


class LogsAlertDestinationSendSerializer(serializers.Serializer):
    hog_function_id = serializers.CharField(
        source="destination_id",
        help_text="The HogFunction the message was sent for. It names the lifecycle event that was sent.",
    )
    sent_at = serializers.DateTimeField(help_text="When the send started.")
    path = serializers.ChoiceField(
        choices=DeliveryPath.choices,
        help_text=(
            "Which delivery path sent it. `native` is the stock message sent by the alerts platform. "
            "`hog_function` is the destination's HogFunction."
        ),
    )
    succeeded = serializers.BooleanField(help_text="Whether the destination accepted the message.")
    error = serializers.CharField(
        allow_null=True,
        help_text=(
            "Why a `native` send failed. Null when it succeeded, and for a `hog_function` send, "
            "whose reason is in the HogFunction's own logs."
        ),
    )


def _build_reason(
    prev_state: AlertState,
    outcome: AlertCheckOutcome,
    window_count: int,
    threshold: int,
    is_above: bool,
    breached: bool,
    recent_window: tuple[bool, ...],
    n: int,
    m: int,
    cooldown_suppressed: bool,
) -> str:
    """Build a human-readable explanation of what happened at this check."""
    op = ">" if is_above else "<"
    count_desc = (
        f"{window_count} {op} {threshold}" if breached else f"{window_count} {'≤' if is_above else '≥'} {threshold}"
    )
    is_n_of_m = not (n == 1 and m == 1)

    if prev_state == AlertState.NOT_FIRING:
        if outcome.new_state == AlertState.FIRING:
            if is_n_of_m:
                breach_count = sum(1 for b in recent_window if b)
                return f"{count_desc}, {breach_count} of last {len(recent_window)} checks breached (need {n} of {m}) — fired"
            return f"{count_desc} — fired"
        if breached and is_n_of_m:
            breach_count = sum(1 for b in recent_window if b)
            return (
                f"{count_desc}, {breach_count} of last {len(recent_window)} checks breached (need {n} of {m}) — waiting"
            )
        return f"{count_desc} — OK"

    if prev_state in (AlertState.FIRING, AlertState.PENDING_RESOLVE):
        if outcome.new_state == AlertState.NOT_FIRING:
            if cooldown_suppressed:
                return f"{count_desc} — resolved (notification suppressed by cooldown)"
            return f"{count_desc} — resolved"
        if outcome.new_state == AlertState.FIRING and breached:
            if cooldown_suppressed:
                return f"{count_desc} — still firing (notification suppressed by cooldown)"
            return f"{count_desc} — still firing"

    return f"{count_desc}"


def _fill_empty_buckets(
    sparse: list[BucketedCount],
    date_from: datetime,
    date_to: datetime,
    interval_minutes: int,
) -> list[BucketedCount]:
    """Fill gaps in sparse bucketed results with zero-count entries.

    ClickHouse GROUP BY only returns buckets that have data. The state machine
    needs to evaluate every check interval to correctly apply N-of-M and cooldown.
    """
    if interval_minutes <= 0:
        return sparse

    expected_buckets = int((date_to - date_from).total_seconds() / (interval_minutes * 60)) + 1
    if expected_buckets > MAX_SIMULATE_BUCKETS:
        raise ValidationError(
            f"Simulation would produce {expected_buckets} buckets (max {MAX_SIMULATE_BUCKETS}). "
            "Use a shorter date range or larger window."
        )

    # ClickHouse returns naive datetimes; normalize to UTC for both lookup and output
    existing = {
        (b.timestamp.replace(tzinfo=UTC) if b.timestamp.tzinfo is None else b.timestamp): BucketedCount(
            timestamp=b.timestamp.replace(tzinfo=UTC) if b.timestamp.tzinfo is None else b.timestamp,
            count=b.count,
        )
        for b in sparse
    }
    interval = dt.timedelta(minutes=interval_minutes)

    # Align date_from to the bucket boundary
    epoch = datetime(2000, 1, 1, tzinfo=UTC)
    seconds = int((date_from - epoch).total_seconds())
    interval_seconds = interval_minutes * 60
    aligned_seconds = (seconds // interval_seconds) * interval_seconds
    cursor = epoch + dt.timedelta(seconds=aligned_seconds)

    result: list[BucketedCount] = []
    while cursor <= date_to:
        if cursor in existing:
            result.append(existing[cursor])
        elif cursor >= date_from:
            result.append(BucketedCount(timestamp=cursor, count=0))
        cursor += interval
    return result


@frozen
class _EventWindow(Sequence[LogsAlertEvent]):
    """The newest rows of a history merged from two sources, sized as the whole history.

    `LimitOffsetPagination` pages it as it pages a list: it takes its length, then slices one page.
    It holds only the rows up to the end of the page the request asked for.
    """

    newest: Sequence[LogsAlertEvent]
    total: int

    def __len__(self) -> int:
        return self.total

    @overload
    def __getitem__(self, index: int) -> LogsAlertEvent: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[LogsAlertEvent]: ...

    def __getitem__(self, index: int | slice) -> LogsAlertEvent | Sequence[LogsAlertEvent]:
        return self.newest[index]


def _with_platform_checks(
    alert: LogsAlertConfiguration, events: QuerySet[LogsAlertEvent], *, kind: str | None, rows_needed: int
) -> QuerySet[LogsAlertEvent] | _EventWindow:
    """`events` with the platform's checks in place of the shadow ones, newest first.

    A logs check row written after the cutover is the shadow evaluation, so it is left out.
    `rows_needed` is the end of the requested page, because a merged page needs that many rows
    from each source.

    Returns `events` unchanged for an alert the logs stack owns, and when ClickHouse fails, because
    the shadow checks are a better answer than a failed list.
    """
    cutover_at = alert.owner_changed_at
    if not alert.platform_owned or cutover_at is None:
        return events
    if kind is not None and kind != LogsAlertEvent.Kind.CHECK:
        return events
    # The viewset adds the same tie-break to a queryset it pages, which this merge bypasses.
    logs_events = stable_queryset_ordering(events.exclude(kind=LogsAlertEvent.Kind.CHECK, created_at__gte=cutover_at))
    try:
        checks = platform_check_rows(team_id=alert.team_id, alert_id=alert.id, since=cutover_at, limit=rows_needed)
    except Exception as error:
        capture_exception(error)
        return events
    if checks is None:
        return events
    merged = [*logs_events[:rows_needed], *(_as_logs_event(alert, row) for row in checks.rows)]
    merged.sort(key=lambda event: event.created_at, reverse=True)
    return _EventWindow(newest=merged[:rows_needed], total=logs_events.count() + checks.total)


def _as_logs_event(alert: LogsAlertConfiguration, row: PlatformCheckRow) -> LogsAlertEvent:
    """An unsaved row in the shape `LogsAlertEventSerializer` reads."""
    return LogsAlertEvent(
        id=row.id,
        alert=alert,
        kind=LogsAlertEvent.Kind.CHECK,
        created_at=row.created_at,
        state_before=row.state_before,
        state_after=row.state_after,
        threshold_breached=row.threshold_breached,
        result_count=row.result_count,
        error_message=row.error_message,
        query_duration_ms=row.query_duration_ms,
    )


@extend_schema_view(list=extend_schema(parameters=[LogsAlertListQuerySerializer]))
class LogsAlertViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "logs"
    queryset = LogsAlertConfiguration.objects.all().order_by("-created_at")
    serializer_class = LogsAlertConfigurationSerializer
    lookup_field = "id"

    def get_serializer_class(self) -> type[LogsAlertConfigurationSerializer]:
        # Only a single-alert read carries the destinations. Every other action would pay
        # for their stored inputs without a caller that wants them.
        if self.action == "retrieve":
            return LogsAlertConfigurationDetailSerializer
        return LogsAlertConfigurationSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        if self.action == "list":
            query_serializer = LogsAlertListQuerySerializer(data=self.request.query_params)
            query_serializer.is_valid(raise_exception=True)
            created_by = query_serializer.validated_data.get("created_by")
            if created_by:
                queryset = queryset.filter(created_by__uuid=created_by)

        # Correlated subquery so list/retrieve can surface `last_error_message` in a
        # single round-trip instead of one extra query per alert.
        latest_error = (
            LogsAlertEvent.objects.filter(
                alert=OuterRef("pk"),
                kind=LogsAlertEvent.Kind.CHECK,
                error_message__isnull=False,
            )
            .order_by("-created_at")
            .values("error_message")[:1]
        )
        # Anchor the prefetch window and the serializer's window to the same instant so
        # they can't drift mid-request. Use a precise `now - 24h` (no hour quantization)
        # — the frontend maps event timestamps to x-coordinates directly.
        self._state_timeline_window = _state_timeline_window_bounds()
        window_start, _ = self._state_timeline_window
        # Scope by team so Postgres can use the team index on the alert FK join — without
        # it the prefetch scans every team's events.
        timeline_events = (
            LogsAlertEvent.objects.filter(alert__team_id=self.team_id, created_at__gte=window_start)
            # alert_id is required — Prefetch groups events by FK after fetching; deferring
            # it triggers a lazy load per event (N+1).
            .only("alert_id", "kind", "created_at", "state_before", "state_after")
            .order_by("created_at")
        )
        # Latest ENABLE/DISABLE at-or-before window_start — lets the serializer seed
        # `enabled` correctly when the window has no toggle events.
        latest_pre_window_toggle = (
            LogsAlertEvent.objects.filter(
                alert=OuterRef("pk"),
                kind__in=(LogsAlertEvent.Kind.ENABLE, LogsAlertEvent.Kind.DISABLE),
                created_at__lt=window_start,
            )
            .order_by("-created_at")
            .values("kind")[:1]
        )
        return (
            queryset.filter(team_id=self.team_id)
            .annotate(
                _latest_error_message=Subquery(latest_error),
                _pre_window_toggle_kind=Subquery(latest_pre_window_toggle),
            )
            .prefetch_related(Prefetch("events", queryset=timeline_events, to_attr="_state_timeline_events"))
        )

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        context["state_timeline_window"] = (
            getattr(self, "_state_timeline_window", None) or _state_timeline_window_bounds()
        )
        return context

    def _get_locked_alert(self) -> LogsAlertConfiguration:
        queryset = self.filter_queryset(self.get_queryset()).select_for_update()
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        alert = get_object_or_404(queryset, **{self.lookup_field: self.kwargs[lookup_url_kwarg]})
        self.check_object_permissions(self.request, alert)
        return alert

    def update(self, request: Request, *args: object, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        with transaction.atomic():
            instance = self._get_locked_alert()
            serializer = self.get_serializer(instance, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)

            prefetched_objects_cache = getattr(instance, "_prefetched_objects_cache", None)
            if prefetched_objects_cache:
                prefetched_objects_cache.clear()

        return Response(serializer.data)

    @extend_schema(
        request=LogsAlertCreateDestinationSerializer,
        responses={201: LogsAlertDestinationResponseSerializer},
        description=(
            "Create a notification destination for this alert. One HogFunction is created per alert event kind "
            "(firing, resolved, ...) atomically. A PagerDuty destination gets the incident opened and incident closed "
            "kinds instead. They follow every start and end of a firing, cooldown included, so each incident it "
            "opens is resolved."
        ),
    )
    @action(detail=True, methods=["POST"], url_path="destinations", required_scopes=["logs:write"])
    def create_destination(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = LogsAlertCreateDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = cast(AlertDestinationData, serializer.validated_data)
        event_kinds = [
            kind for kind in EVENT_KINDS if destination_handles_event_kind(data["type"], EVENT_KIND_CONFIG[kind])
        ]

        with transaction.atomic():
            alert = self._get_locked_alert()
            configs = [
                build_alert_destination_config(
                    spec=EVENT_KIND_CONFIG[kind],
                    alert_id=str(alert.id),
                    alert_name=alert.name,
                    data=data,
                    slack_context_elements=LOGS_ALERT_SLACK_CONTEXT_ELEMENTS,
                )
                for kind in event_kinds
            ]
            try:
                hog_function_ids = create_alert_destination_hog_functions(
                    configs,
                    team_id=alert.team_id,
                    created_by_id=cast(User, request.user).id,
                    alert_id=str(alert.id),
                    allowed_event_ids=LOGS_ALERT_EVENT_IDS,
                )
            except AlertDestinationValidationError as error:
                raise as_drf_validation_error(error)

        report_user_action(
            request.user,
            "logs alert destination created",
            {"alert_id": str(alert.id), "type": data["type"], "event_kinds": event_kinds},
            request=request,
        )
        response = LogsAlertDestinationResponseSerializer({"hog_function_ids": list(hog_function_ids)})
        return Response(response.data, status=201)

    @extend_schema(
        request=LogsAlertDeleteDestinationSerializer,
        responses={204: None},
        description="Delete a notification destination by deleting its HogFunction group atomically.",
    )
    @action(detail=True, methods=["POST"], url_path="destinations/delete", required_scopes=["logs:write"])
    def delete_destination(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = LogsAlertDeleteDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hog_function_ids = serializer.validated_data["hog_function_ids"]

        with transaction.atomic():
            alert = self._get_locked_alert()
            groups = list_alert_destination_groups(
                team_id=self.team_id,
                alert_id=str(alert.id),
                allowed_event_ids=LOGS_ALERT_EVENT_IDS,
            )
            largest_server_group = max((len(group.hog_function_ids) for group in groups), default=0)
            if len(hog_function_ids) > max(MAX_DESTINATION_IDS_PER_DELETE_REQUEST, largest_server_group):
                raise ValidationError({"hog_function_ids": "Too many destination IDs."})
            try:
                soft_delete_alert_destinations(
                    team_id=self.team_id,
                    alert_id=str(alert.id),
                    allowed_event_ids=LOGS_ALERT_EVENT_IDS,
                    hog_function_ids=hog_function_ids,
                )
            except AlertDestinationValidationError as error:
                raise as_drf_validation_error(error)

        report_user_action(
            request.user,
            "logs alert destination deleted",
            {"alert_id": str(alert.id), "count": len(hog_function_ids)},
            request=request,
        )
        return Response(status=204)

    @extend_schema(
        parameters=[LogsAlertDestinationSendsQuerySerializer],
        responses={200: LogsAlertDestinationSendSerializer(many=True)},
        description=(
            "The last messages sent to one destination of this alert in the past 7 days, newest first, "
            "on both delivery paths, with whether each one succeeded."
        ),
    )
    @action(
        detail=True,
        methods=["GET"],
        url_path="destinations/sends",
        required_scopes=["logs:read"],
        pagination_class=None,
    )
    def destination_sends(self, request: Request, *args: object, **kwargs: object) -> Response:
        alert = self.get_object()
        query = LogsAlertDestinationSendsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        owned = owned_alert_destination_ids(
            team_id=self.team_id,
            alert_id=str(alert.id),
            allowed_event_ids=LOGS_ALERT_EVENT_IDS,
            hog_function_ids=query.validated_data["hog_function_ids"],
        )
        sends = recent_destination_sends(
            team_id=self.team_id, destination_ids=[str(i) for i in owned], limit=MAX_DESTINATION_SENDS
        )
        return Response(LogsAlertDestinationSendSerializer(sends, many=True).data)

    @extend_schema(
        request=None,
        responses={200: LogsAlertEventSerializer(many=True)},
        description=(
            "Paginated event history for this alert, newest first. Returns state transitions, "
            "errored checks, and user-initiated control-plane rows (reset, enable/disable, "
            "snooze/unsnooze, threshold change) — quiet no-op check rows (where state didn't "
            "change and there was no error) are filtered out since only the last 10 are kept "
            "and they carry no forensic value. Optional `?kind=...` narrows to a single kind. "
            "For an alert the alerts platform evaluates, checks since it took the alert over come "
            "from the platform's check history."
        ),
    )
    @action(detail=True, methods=["GET"], url_path="events", required_scopes=["logs:read"])
    def events(self, request: Request, *args: object, **kwargs: object) -> Response:
        alert = self.get_object()
        queryset = (
            LogsAlertEvent.objects.filter(alert=alert)
            .filter(
                ~Q(kind=LogsAlertEvent.Kind.CHECK) | Q(error_message__isnull=False) | ~Q(state_before=F("state_after"))
            )
            .order_by("-created_at")
        )

        kind = request.query_params.get("kind")
        if kind is not None:
            valid_kinds = LogsAlertEvent.Kind.values
            if kind not in valid_kinds:
                raise ValidationError({"kind": f"Must be one of {sorted(valid_kinds)}."})
            queryset = queryset.filter(kind=kind)

        paginator = cast(LimitOffsetPagination, self.paginator)
        rows_needed = paginator.get_offset(request) + (paginator.get_limit(request) or 0)
        if alert.platform_owned and rows_needed > MAX_MERGED_EVENT_ROWS:
            raise ValidationError({"offset": f"Offset plus limit must be at most {MAX_MERGED_EVENT_ROWS}."})
        history = _with_platform_checks(alert, queryset, kind=kind, rows_needed=rows_needed)
        page = self.paginate_queryset(history)
        if page is not None:
            serializer = LogsAlertEventSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = LogsAlertEventSerializer(history, many=True)
        return Response(serializer.data)

    @extend_schema(
        request=None,
        responses={200: LogsAlertConfigurationSerializer},
        description="Reset a broken alert. Clears the consecutive-failure counter and schedules an immediate recheck.",
    )
    @action(detail=True, methods=["POST"], url_path="reset", required_scopes=["logs:write"])
    def reset(self, request: Request, *args: object, **kwargs: object) -> Response:
        with transaction.atomic():
            # The logs row first, then the platform copy: the cutover and rollback take the two
            # locks in that order, and the opposite order deadlocks against them.
            alert = self._get_locked_alert()
            previous_failures = alert.consecutive_failures
            if alert.platform_owned:
                # The platform skips a broken alert, so the reset has to reach its copy. Its state
                # decides, because the logs row stops moving once the shadow ends.
                platform_failures = reset_broken(
                    team_id=alert.team_id, legacy_configuration_id=alert.id, at=timezone.now()
                )
                if platform_failures is None:
                    raise ValidationError({"state": "Only broken alerts can be reset."})
                previous_failures = platform_failures
            try:
                outcome = apply_user_reset(alert.to_snapshot())
            except InvalidTransition:
                if not alert.platform_owned:
                    raise ValidationError({"state": "Only broken alerts can be reset."})
                outcome = None
            if outcome is not None:
                update_fields = apply_outcome(alert, outcome, kind=LogsAlertEvent.Kind.RESET)
                update_fields.extend(alert.clear_next_check())
                alert.save(update_fields=update_fields)
            else:
                # The logs row did not move, so nothing else records the reset that the alert's
                # timeline needs. The platform's history writes no row for it either.
                LogsAlertEvent.objects.create(
                    alert=alert,
                    kind=LogsAlertEvent.Kind.RESET,
                    threshold_breached=False,
                    state_before=LogsAlertConfiguration.State.BROKEN,
                    state_after=LogsAlertConfiguration.State.NOT_FIRING,
                )
            # The model's auto-signal skips these fields (signal_exclusions silences
            # engine-driven churn) so we log the user-initiated reset explicitly.
            log_activity(
                organization_id=self.team.organization_id,
                team_id=self.team_id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
                item_id=alert.id,
                scope="LogsAlertConfiguration",
                activity="reset",
                detail=Detail(
                    name=alert.name,
                    changes=[
                        Change(
                            type="LogsAlertConfiguration",
                            action="changed",
                            field="state",
                            before="broken",
                            after="not_firing",
                        ),
                        Change(
                            type="LogsAlertConfiguration",
                            action="changed",
                            field="consecutive_failures",
                            before=previous_failures,
                            after=0,
                        ),
                    ],
                ),
            )
        report_user_action(request.user, "logs alert reset", {"alert_id": str(alert.id)}, request=request)
        return Response(self.get_serializer(alert).data)

    @extend_schema(
        request=LogsAlertSimulateRequestSerializer,
        responses={200: LogsAlertSimulateResponseSerializer},
        description="Simulate a logs alert on historical data using the full state machine. "
        "Read-only — no alert check records are created.",
    )
    @action(detail=False, methods=["POST"], url_path="simulate", required_scopes=["logs:read"])
    def simulate(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = LogsAlertSimulateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        date_from_dt = relative_date_parse(data["date_from"], ZoneInfo("UTC"))
        date_to_dt = datetime.now(UTC)
        window_minutes = data["window_minutes"]

        fake_alert = LogsAlertConfiguration(
            team=self.team,
            filters=data["filters"],
            threshold_count=data["threshold_count"],
            threshold_operator=data["threshold_operator"],
            window_minutes=window_minutes,
            check_interval_minutes=data["check_interval_minutes"],
        )
        cadence_minutes = fake_alert.check_interval_minutes

        sparse_buckets: list[BucketedCount] = AlertCheckQuery(
            team=self.team,
            alert=fake_alert,
            date_from=date_from_dt,
            date_to=date_to_dt,
        ).execute_bucketed(interval_minutes=cadence_minutes, limit=MAX_SIMULATE_BUCKETS)

        cadence_buckets = _fill_empty_buckets(sparse_buckets, date_from_dt, date_to_dt, cadence_minutes)

        # ALLOWED_WINDOW_MINUTES is bounded below by the configured cadence,
        # so integer division here is always >= 1.
        buckets_per_window = window_minutes // cadence_minutes
        counts = [b.count for b in cadence_buckets]
        rolling_counts: list[int] = []
        # Bucket i represents `[T_i, T_i + check_interval)`. The actual evaluator
        # at moment T queries `[T - window, T)` — purely past — so the simulator's
        # rolling sum at bucket time T_i must exclude bucket i (which holds future
        # data) and sum the previous `buckets_per_window` buckets ending just
        # before T_i. Without this, the simulator looks `check_interval` minutes
        # into the future and produces fire/resolve transitions that don't match
        # production.
        for i in range(len(counts)):
            window_start = max(0, i - buckets_per_window)
            rolling_counts.append(sum(counts[window_start:i]))

        threshold = data["threshold_count"]
        is_above = data["threshold_operator"] == LogsAlertConfiguration.ThresholdOperator.ABOVE
        evaluation_periods = data.get("evaluation_periods", 1)
        datapoints_to_alarm = data.get("datapoints_to_alarm", 1)
        cooldown_minutes = data.get("cooldown_minutes", 0)

        # Run the full state machine over the bucketed results
        snapshot = AlertSnapshot(
            state=AlertState.NOT_FIRING,
            evaluation_periods=evaluation_periods,
            datapoints_to_alarm=datapoints_to_alarm,
            cooldown_minutes=cooldown_minutes,
            last_notified_at=None,
            snooze_until=None,
            consecutive_failures=0,
            recent_events_breached=(),
        )

        result_buckets = []
        fire_count = 0
        resolve_count = 0

        for i, bucket in enumerate(cadence_buckets):
            window_count = rolling_counts[i]
            breached = window_count > threshold if is_above else window_count < threshold
            check = CheckResult(result_count=window_count, threshold_breached=breached)
            prev_state = snapshot.state
            outcome: AlertCheckOutcome = evaluate_alert_check(snapshot, check, bucket.timestamp)

            if outcome.notification == NotificationAction.FIRE:
                fire_count += 1
            elif outcome.notification == NotificationAction.RESOLVE:
                resolve_count += 1

            # Build the recent window including this check (same as what the state machine saw)
            recent = (breached, *snapshot.recent_events_breached)[:evaluation_periods]

            # Detect cooldown suppression: state changed but notification was suppressed
            cooldown_suppressed = (
                outcome.notification == NotificationAction.NONE
                and outcome.new_state != prev_state
                and outcome.new_state in (AlertState.FIRING, AlertState.NOT_FIRING)
                and prev_state in (AlertState.FIRING, AlertState.NOT_FIRING, AlertState.PENDING_RESOLVE)
                and breached != (prev_state == AlertState.NOT_FIRING)
            )

            reason = _build_reason(
                prev_state=prev_state,
                outcome=outcome,
                window_count=window_count,
                threshold=threshold,
                is_above=is_above,
                breached=breached,
                recent_window=recent,
                n=datapoints_to_alarm,
                m=evaluation_periods,
                cooldown_suppressed=cooldown_suppressed,
            )

            result_buckets.append(
                {
                    "timestamp": bucket.timestamp.isoformat(),
                    "count": window_count,
                    "threshold_breached": breached,
                    "state": outcome.new_state.value,
                    "notification": outcome.notification.value,
                    "reason": reason,
                }
            )

            # Advance the snapshot for the next iteration
            snapshot = AlertSnapshot(
                state=outcome.new_state,
                evaluation_periods=evaluation_periods,
                datapoints_to_alarm=datapoints_to_alarm,
                cooldown_minutes=cooldown_minutes,
                last_notified_at=bucket.timestamp if outcome.update_last_notified_at else snapshot.last_notified_at,
                snooze_until=None,
                consecutive_failures=outcome.consecutive_failures,
                recent_events_breached=recent,
            )

        response_data = {
            "buckets": result_buckets,
            "fire_count": fire_count,
            "resolve_count": resolve_count,
            "total_buckets": len(result_buckets),
            "threshold_count": threshold,
            "threshold_operator": data["threshold_operator"],
        }

        response_serializer = LogsAlertSimulateResponseSerializer(response_data)
        return Response(response_serializer.data)

    def _track(self, action: Literal["created", "updated", "deleted"], instance: LogsAlertConfiguration) -> None:
        report_user_action(
            self.request.user,
            f"alert {action}",
            {
                "alert_id": str(instance.id),
                "alert_name": instance.name,
                "config_type": "LogsAlertConfig",
                "check_interval_minutes": instance.check_interval_minutes,
                "enabled": instance.enabled,
                "threshold_count": instance.threshold_count,
                "threshold_operator": instance.threshold_operator,
                "window_minutes": instance.window_minutes,
            },
            team=self.team,
            request=self.request,
        )

    def perform_create(self, serializer) -> None:
        self._track("created", serializer.save())

    def perform_update(self, serializer) -> None:
        self._track("updated", serializer.save())

    def perform_destroy(self, instance: LogsAlertConfiguration) -> None:
        if delete_alert(team_id=instance.team_id, alert_id=instance.id):
            # Robust, so an analytics failure, such as a malformed Referer, cannot fail a committed delete.
            transaction.on_commit(lambda: self._track("deleted", instance), robust=True)
