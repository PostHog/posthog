"""DRF viewset for tracing alert configuration and history.

Scoped-down relative to `products/logs/backend/presentation/views/alerts_api.py`:
no `destinations` or `simulate` actions yet — those depend on notification
destination wiring (HogFunction template registration, allowed event ids) that
doesn't exist for tracing yet. `reset` skips the `log_activity` audit-trail call
logs makes, since `TracingAlertConfiguration` isn't registered in
`posthog/models/activity_logging/activity_log.py`'s scopes (the model also
doesn't use `ModelActivityMixin` — see products/tracing/backend/models.py).
"""

from __future__ import annotations

import datetime as dt
from datetime import UTC, datetime
from typing import Any, Final, TypedDict, cast

from django.db import transaction
from django.db.models import F, OuterRef, Prefetch, Q, QuerySet, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone

from drf_spectacular.utils import extend_schema, extend_schema_field
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import TracingAlertFilters

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models.team.team import Team
from posthog.permissions import PostHogFeatureFlagPermission

from products.alerts.backend.facade.api import AlertScheduleRestriction, validate_and_normalize_schedule_restriction
from products.tracing.backend.alert_state_machine import (
    InvalidTransition,
    apply_disable,
    apply_enable,
    apply_outcome,
    apply_snooze,
    apply_threshold_change,
    apply_unsnooze,
    apply_user_reset,
)
from products.tracing.backend.alert_utils import next_allowed_check_at
from products.tracing.backend.models import MAX_EVALUATION_PERIODS, TracingAlertConfiguration, TracingAlertEvent

ALLOWED_WINDOW_MINUTES = {5, 10, 15, 30, 60}
MAX_ALERTS_PER_TEAM = 20
STATE_TIMELINE_LOOKBACK_HOURS = 24
_SENTINEL: Final = object()
_NOT_ANNOTATED: Final = object()


def _state_timeline_window_bounds() -> tuple[datetime, datetime]:
    end = datetime.now(UTC)
    return end - dt.timedelta(hours=STATE_TIMELINE_LOOKBACK_HOURS), end


def _any_field_changed(instance: TracingAlertConfiguration, validated_data: dict, fields: set[str]) -> bool:
    return any(f in validated_data and validated_data[f] != getattr(instance, f) for f in fields)


def _validate_filters(filters: dict) -> None:
    """Cross-field requirement that at least one filter is present.

    Per-field shape validation is handled by `TracingAlertFiltersField`, which runs
    `TracingAlertFilters.model_validate` on the raw input.
    """
    if not isinstance(filters, dict):
        raise ValidationError({"filters": "Must be a JSON object."})
    has_services = bool(filters.get("serviceNames"))
    has_error_only = bool(filters.get("errorOnly"))
    has_filter_group = bool(filters.get("filterGroup"))
    if not (has_services or has_error_only or has_filter_group):
        raise ValidationError({"filters": "At least one filter is required (serviceNames, errorOnly, or filterGroup)."})


class TracingAlertListQuerySerializer(serializers.Serializer):
    created_by = serializers.UUIDField(
        required=False,
        help_text="Only return tracing alerts created by the user with this UUID.",
    )


class TracingAlertStateIntervalSerializer(serializers.Serializer):
    start = serializers.DateTimeField(help_text="Interval start (UTC, inclusive).")
    end = serializers.DateTimeField(help_text="Interval end (UTC, exclusive).")
    state = serializers.ChoiceField(
        choices=TracingAlertConfiguration.State.choices,
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


@extend_schema_field(TracingAlertFilters)  # type: ignore[arg-type]
class TracingAlertFiltersField(serializers.JSONField):
    """JSONField typed against the `TracingAlertFilters` Pydantic schema.

    Annotating with `@extend_schema_field(TracingAlertFilters)` is what makes the
    generated OpenAPI spec — and downstream MCP zod schemas — surface the actual
    shape (serviceNames / errorOnly / filterGroup) instead of an opaque blob.
    """

    def to_internal_value(self, data: dict | list) -> dict:
        value = super().to_internal_value(data)
        if not isinstance(value, dict):
            raise serializers.ValidationError("Must be a JSON object.")
        try:
            TracingAlertFilters.model_validate(value)
        except PydanticValidationError as e:
            first = e.errors()[0]
            location = ".".join(str(p) for p in first["loc"]) or "filters"
            raise serializers.ValidationError(f"Invalid filters shape at `{location}`: {first['msg']}") from e
        return value


@extend_schema_field(AlertScheduleRestriction)  # type: ignore[arg-type]
class ScheduleRestrictionField(serializers.JSONField):
    pass


class TracingAlertConfigurationSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for this alert.")
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
    alert_type = serializers.ChoiceField(
        choices=TracingAlertConfiguration.AlertType.choices,
        default=TracingAlertConfiguration.AlertType.THRESHOLD,
        help_text="Alert evaluation mode. Only 'threshold' is supported today; reserved for a future "
        "statistical-anomaly mode.",
    )
    filters = TracingAlertFiltersField(
        required=False,
        help_text="Filter criteria against trace_spans. Must contain at least one of: serviceNames "
        "(list of service name strings), errorOnly (boolean), or filterGroup (property filter group "
        "object). May be empty on draft alerts (enabled=false).",
    )
    threshold_count = serializers.IntegerField(
        min_value=0,
        default=100,
        help_text="Number of matching spans that constitutes a threshold breach within the evaluation "
        "window. Defaults to 100. Use 0 with the 'above' operator to fire on any matching span.",
    )
    first_enabled_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the alert was first enabled. Null means the alert is still in draft state.",
    )
    threshold_operator = serializers.ChoiceField(
        choices=TracingAlertConfiguration.ThresholdOperator.choices,
        default=TracingAlertConfiguration.ThresholdOperator.ABOVE,
        help_text="Whether the alert fires when the count is above or below the threshold.",
    )
    window_minutes = serializers.IntegerField(
        default=5,
        help_text="Time window in minutes over which matching spans are counted. Allowed values: 5, 10, 15, 30, 60.",
    )
    check_interval_minutes = serializers.IntegerField(
        read_only=True,
        help_text="How often the alert is evaluated, in minutes. Server-managed.",
    )
    state = serializers.ChoiceField(
        choices=TracingAlertConfiguration.State.choices,
        read_only=True,
        help_text="Current alert state: not_firing, firing, pending_resolve, errored, snoozed, or broken. Server-managed.",
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
        help_text="Minimum minutes between repeated notifications after the alert fires. 0 means no cooldown.",
    )
    schedule_restriction = ScheduleRestrictionField(
        required=False,
        allow_null=True,
        help_text="Blocked local time windows when the alert must not run. Times use the project timezone. "
        "Null disables quiet hours.",
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
        help_text="Error message from the most recent errored check, or null if the alert's most recent "
        "check was successful.",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the alert was created.")
    created_by = UserBasicSerializer(read_only=True)
    updated_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the alert was last modified.",
    )
    state_timeline = serializers.SerializerMethodField(
        help_text=(
            f"Continuous state intervals over the last {STATE_TIMELINE_LOOKBACK_HOURS}h, ordered oldest-first. "
            "Each interval covers a span during which (state, enabled) was constant. Drives the 'Last 24h' "
            "status bar on the alert list."
        ),
    )

    @extend_schema_field(TracingAlertStateIntervalSerializer(many=True))
    def get_state_timeline(self, obj: TracingAlertConfiguration) -> list[StateInterval]:
        window = self.context.get("state_timeline_window") or _state_timeline_window_bounds()
        window_start, window_end = window

        events = getattr(obj, "_state_timeline_events", None)
        if events is None:
            events = list(
                TracingAlertEvent.objects.filter(alert=obj, created_at__gte=window_start)
                .order_by("created_at")
                .only("kind", "created_at", "state_before", "state_after")
            )

        seed_state = events[0].state_before if events else obj.state

        pre_window_toggle = getattr(obj, "_pre_window_toggle_kind", _NOT_ANNOTATED)
        if pre_window_toggle is _NOT_ANNOTATED:
            pre_window_toggle = (
                TracingAlertEvent.objects.filter(
                    alert=obj,
                    kind__in=(TracingAlertEvent.Kind.ENABLE, TracingAlertEvent.Kind.DISABLE),
                    created_at__lt=window_start,
                )
                .order_by("-created_at")
                .values_list("kind", flat=True)
                .first()
            )
        if pre_window_toggle is not None:
            seed_enabled = pre_window_toggle == TracingAlertEvent.Kind.ENABLE
        else:
            first_in_window_toggle = next(
                (e for e in events if e.kind in (TracingAlertEvent.Kind.ENABLE, TracingAlertEvent.Kind.DISABLE)),
                None,
            )
            if first_in_window_toggle is not None:
                seed_enabled = first_in_window_toggle.kind == TracingAlertEvent.Kind.DISABLE
            else:
                seed_enabled = obj.enabled

        intervals: list[StateInterval] = []
        current_start = window_start
        current_state = seed_state
        current_enabled = seed_enabled

        for event in events:
            if event.kind == TracingAlertEvent.Kind.ENABLE:
                new_enabled, new_state = True, event.state_after
            elif event.kind == TracingAlertEvent.Kind.DISABLE:
                new_enabled, new_state = False, event.state_after
            else:
                new_enabled, new_state = current_enabled, event.state_after

            if new_state == current_state and new_enabled == current_enabled:
                continue

            intervals.append(
                {"start": current_start, "end": event.created_at, "state": current_state, "enabled": current_enabled}
            )
            current_start = event.created_at
            current_state = new_state
            current_enabled = new_enabled

        intervals.append(
            {"start": current_start, "end": window_end, "state": current_state, "enabled": current_enabled}
        )
        return intervals

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_last_error_message(self, obj: TracingAlertConfiguration) -> str | None:
        annotated = getattr(obj, "_latest_error_message", _NOT_ANNOTATED)
        if annotated is not _NOT_ANNOTATED:
            return cast(str | None, annotated)
        return (
            TracingAlertEvent.objects.filter(
                alert=obj,
                kind=TracingAlertEvent.Kind.CHECK,
                error_message__isnull=False,
            )
            .order_by("-created_at")
            .values_list("error_message", flat=True)
            .first()
        )

    class Meta:
        model = TracingAlertConfiguration
        fields = [
            "id",
            "name",
            "enabled",
            "alert_type",
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

    def update(self, instance: TracingAlertConfiguration, validated_data: dict) -> TracingAlertConfiguration:
        if "name" in validated_data and not validated_data.get("name", "").strip():
            validated_data["name"] = "Untitled alert"

        snooze_data = validated_data.pop("snooze_until", _SENTINEL)

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

        with transaction.atomic():
            snapshot = instance.to_snapshot()
            if enabled_change is True:
                if instance.first_enabled_at is None:
                    instance.first_enabled_at = timezone.now()
                    if "first_enabled_at" not in validated_data:
                        validated_data["first_enabled_at"] = instance.first_enabled_at
                apply_outcome(instance, apply_enable(snapshot), kind=TracingAlertEvent.Kind.ENABLE)
            elif enabled_change is False:
                apply_outcome(instance, apply_disable(snapshot), kind=TracingAlertEvent.Kind.DISABLE)
            elif snooze_data is not _SENTINEL:
                if snooze_data is None:
                    apply_outcome(instance, apply_unsnooze(snapshot), kind=TracingAlertEvent.Kind.UNSNOOZE)
                else:
                    apply_outcome(instance, apply_snooze(snapshot), kind=TracingAlertEvent.Kind.SNOOZE)
            elif threshold_changed:
                apply_outcome(instance, apply_threshold_change(snapshot), kind=TracingAlertEvent.Kind.THRESHOLD_CHANGE)

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

            return super().update(instance, validated_data)

    def create(self, validated_data: dict) -> TracingAlertConfiguration:
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user

        if not validated_data.get("name", "").strip():
            validated_data["name"] = "Untitled alert"

        if validated_data.get("enabled", True):
            validated_data["first_enabled_at"] = timezone.now()

        with transaction.atomic():
            team = Team.objects.select_for_update().get(id=validated_data["team_id"])
            count = TracingAlertConfiguration.objects.unscoped().filter(team_id=validated_data["team_id"]).count()
            if count >= MAX_ALERTS_PER_TEAM:
                raise ValidationError(f"Maximum number of alerts ({MAX_ALERTS_PER_TEAM}) reached for this team.")
            if schedule_restriction := validated_data.get("schedule_restriction"):
                validated_data["next_check_at"] = next_allowed_check_at(
                    datetime.now(UTC),
                    team_timezone=team.timezone,
                    schedule_restriction=schedule_restriction,
                )
            return super().create(validated_data)


class TracingAlertEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = TracingAlertEvent
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


class TracingAlertViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "tracing"
    # Fail-closed manager raises if `.all()` runs at import; the real per-request
    # scoping happens in safely_get_queryset. Mirrors TracingViewViewSet.
    queryset = TracingAlertConfiguration.objects.unscoped()
    serializer_class = TracingAlertConfigurationSerializer
    lookup_field = "id"
    posthog_feature_flag = "tracing-alerting"
    permission_classes = [PostHogFeatureFlagPermission]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        if self.action == "list":
            query_serializer = TracingAlertListQuerySerializer(data=self.request.query_params)
            query_serializer.is_valid(raise_exception=True)
            created_by = query_serializer.validated_data.get("created_by")
            if created_by:
                queryset = queryset.filter(created_by__uuid=created_by)

        latest_error = (
            TracingAlertEvent.objects.filter(
                alert=OuterRef("pk"),
                kind=TracingAlertEvent.Kind.CHECK,
                error_message__isnull=False,
            )
            .order_by("-created_at")
            .values("error_message")[:1]
        )
        self._state_timeline_window = _state_timeline_window_bounds()
        window_start, _ = self._state_timeline_window
        timeline_events = (
            TracingAlertEvent.objects.filter(alert__team_id=self.team_id, created_at__gte=window_start)
            .only("alert_id", "kind", "created_at", "state_before", "state_after")
            .order_by("created_at")
        )
        latest_pre_window_toggle = (
            TracingAlertEvent.objects.filter(
                alert=OuterRef("pk"),
                kind__in=(TracingAlertEvent.Kind.ENABLE, TracingAlertEvent.Kind.DISABLE),
                created_at__lt=window_start,
            )
            .order_by("-created_at")
            .values("kind")[:1]
        )
        return (
            TracingAlertConfiguration.objects.for_team(self.team_id)
            .order_by("-created_at")
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

    def _get_locked_alert(self) -> TracingAlertConfiguration:
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
        request=None,
        responses={200: TracingAlertEventSerializer(many=True)},
        description=(
            "Paginated event history for this alert, newest first. Returns state transitions, "
            "errored checks, and user-initiated control-plane rows (reset, enable/disable, "
            "snooze/unsnooze, threshold change) — quiet no-op check rows (where state didn't "
            "change and there was no error) are filtered out. Optional `?kind=...` narrows to a "
            "single kind."
        ),
    )
    @action(detail=True, methods=["GET"], url_path="events", required_scopes=["tracing:read"])
    def events(self, request: Request, *args: object, **kwargs: object) -> Response:
        alert = self.get_object()
        queryset = (
            TracingAlertEvent.objects.filter(alert=alert)
            .filter(
                ~Q(kind=TracingAlertEvent.Kind.CHECK)
                | Q(error_message__isnull=False)
                | ~Q(state_before=F("state_after"))
            )
            .order_by("-created_at")
        )

        kind = request.query_params.get("kind")
        if kind is not None:
            valid_kinds = TracingAlertEvent.Kind.values
            if kind not in valid_kinds:
                raise ValidationError({"kind": f"Must be one of {sorted(valid_kinds)}."})
            queryset = queryset.filter(kind=kind)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = TracingAlertEventSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = TracingAlertEventSerializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(
        request=None,
        responses={200: TracingAlertConfigurationSerializer},
        description="Reset a broken alert. Clears the consecutive-failure counter and schedules an immediate recheck.",
    )
    @action(detail=True, methods=["POST"], url_path="reset", required_scopes=["tracing:write"])
    def reset(self, request: Request, *args: object, **kwargs: object) -> Response:
        alert = self.get_object()
        try:
            outcome = apply_user_reset(alert.to_snapshot())
        except InvalidTransition:
            raise ValidationError({"state": "Only broken alerts can be reset."})
        with transaction.atomic():
            update_fields = apply_outcome(alert, outcome, kind=TracingAlertEvent.Kind.RESET)
            update_fields.extend(alert.clear_next_check())
            alert.save(update_fields=update_fields)
        report_user_action(request.user, "tracing alert reset", {"alert_id": str(alert.id)}, request=request)
        return Response(self.get_serializer(alert).data)

    def _track(self, action_name: str, instance: TracingAlertConfiguration) -> None:
        report_user_action(
            self.request.user,
            f"tracing alert {action_name}",
            {
                "alert_id": str(instance.id),
                "alert_name": instance.name,
                "check_interval_minutes": instance.check_interval_minutes,
                "enabled": instance.enabled,
                "threshold_count": instance.threshold_count,
                "threshold_operator": instance.threshold_operator,
                "window_minutes": instance.window_minutes,
            },
            team=self.team,
            request=self.request,
        )

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        self._track("created", serializer.save())

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        self._track("updated", serializer.save())

    def perform_destroy(self, instance: TracingAlertConfiguration) -> None:
        with transaction.atomic():
            locked_instance = (
                TracingAlertConfiguration.objects.unscoped()
                .select_for_update()
                .filter(team_id=instance.team_id, id=instance.id)
                .first()
            )
            if locked_instance is None:
                return
            super().perform_destroy(locked_instance)
            transaction.on_commit(lambda: self._track("deleted", locked_instance), robust=True)
