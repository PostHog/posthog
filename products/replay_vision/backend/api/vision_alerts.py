import os
from datetime import UTC, datetime
from typing import Any, Final, cast

from django.db import transaction
from django.db.models import F, Q, QuerySet
from django.shortcuts import get_object_or_404
from django.utils import timezone

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field, extend_schema_view
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models.team.team import Team

from products.alerts.backend.destinations import count_active_alert_destinations
from products.alerts.backend.facade.api import (
    AlertDestinationData,
    AlertDestinationValidationError,
    AlertScheduleRestriction,
    DestinationType,
    build_alert_destination_config,
    create_alert_destination_hog_functions,
    soft_delete_alert_destinations,
    soft_delete_all_alert_destinations,
    validate_and_normalize_schedule_restriction,
    validate_destination_data,
)
from products.replay_vision.backend.alert_destinations import (
    EVENT_KIND_CONFIG,
    MATCH_EVENT_KINDS,
    METRIC_EVENT_KINDS,
    VISION_ALERT_EVENT_IDS,
    VISION_ALERT_SLACK_CONTEXT_ELEMENTS,
    VISION_DESTINATION_TYPES,
    EventKind,
)
from products.replay_vision.backend.alert_state_machine import (
    InvalidTransition,
    apply_disable,
    apply_enable,
    apply_outcome,
    apply_snooze,
    apply_threshold_change,
    apply_unsnooze,
    apply_user_reset,
)
from products.replay_vision.backend.alert_utils import next_allowed_check_at
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType
from products.replay_vision.backend.models.vision_alert import (
    ALERT_WINDOW_DAYS,
    MIN_CHECK_INTERVAL_MINUTES,
    VisionAlertConfiguration,
    VisionAlertDirection,
    VisionAlertEvent,
    VisionAlertKind,
    VisionAlertMetric,
    VisionAlertState,
)

MAX_ALERTS_PER_TEAM = 20
MAX_DESTINATIONS_PER_ALERT = 5
# Comma-separated team IDs that bypass MAX_ALERTS_PER_TEAM, for internal dogfood projects.
UNCAPPED_ALERT_TEAM_IDS: frozenset[int] = frozenset(
    int(t) for x in os.environ.get("VISION_ALERTS_UNCAPPED_TEAM_IDS", "").split(",") if (t := x.strip()).isdigit()
)

_SENTINEL: Final = object()


def _any_field_changed(instance: VisionAlertConfiguration, validated_data: dict, fields: set[str]) -> bool:
    return any(f in validated_data and validated_data[f] != getattr(instance, f) for f in fields)


@extend_schema_field(AlertScheduleRestriction)  # type: ignore[arg-type]
class ScheduleRestrictionField(serializers.JSONField):
    pass


class VisionAlertSelectionSerializer(serializers.Serializer):
    verdict = serializers.ListField(
        child=serializers.CharField(max_length=100),
        max_length=10,
        required=False,
        help_text="Monitor verdicts to match, e.g. ['yes'].",
    )
    tags = serializers.ListField(
        child=serializers.CharField(max_length=200),
        max_length=20,
        required=False,
        help_text="Classifier tags to match; an observation matches when it carries any of them.",
    )
    min_score = serializers.FloatField(
        required=False,
        help_text="Minimum scorer score (inclusive).",
    )
    max_score = serializers.FloatField(
        required=False,
        help_text="Maximum scorer score (inclusive).",
    )


class VisionAlertConfigurationSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for this alert.")
    scanner_id = TeamScopedPrimaryKeyRelatedField(
        source="scanner",
        queryset=ReplayScanner.objects.all(),
        help_text="Scanner whose observations this alert watches. Immutable after creation.",
    )
    name = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="Untitled alert",
        help_text="Human-readable name for this alert. Defaults to 'Untitled alert' on create when omitted.",
    )
    enabled = serializers.BooleanField(
        default=True,
        help_text="Whether the alert is active. Disabling a metric alert resets its state to not_firing.",
    )
    kind = serializers.ChoiceField(
        choices=VisionAlertKind.choices,
        help_text="'metric' fires when a metric crosses a threshold over a rolling window; "
        "'match' fires on every observation that matches the selection. Immutable after creation.",
    )
    selection = VisionAlertSelectionSerializer(
        required=False,
        help_text="Which observations count. Empty matches every observation of the scanner.",
    )
    metric = serializers.ChoiceField(
        choices=VisionAlertMetric.choices,
        default=VisionAlertMetric.COUNT,
        help_text="Metric alerts only: what to measure over the window. 'avg_score' requires a scorer scanner.",
    )
    direction = serializers.ChoiceField(
        choices=VisionAlertDirection.choices,
        default=VisionAlertDirection.ABOVE,
        help_text="Metric alerts only: whether the alert fires at or above, or at or below, the threshold.",
    )
    threshold = serializers.FloatField(
        required=False,
        allow_null=True,
        help_text="Metric alerts only: the threshold value. Required for metric alerts, must be omitted for match alerts.",
    )
    window_days = serializers.IntegerField(
        default=1,
        help_text=f"Metric alerts only: rolling window in days. Allowed values: {list(ALERT_WINDOW_DAYS)}.",
    )
    check_interval_minutes = serializers.IntegerField(
        default=60,
        min_value=MIN_CHECK_INTERVAL_MINUTES,
        help_text=f"Metric alerts only: evaluation cadence in minutes, at least {MIN_CHECK_INTERVAL_MINUTES}.",
    )
    state = serializers.ChoiceField(
        choices=VisionAlertState.choices,
        read_only=True,
        help_text="Current lifecycle state. Always not_firing for match alerts. Server-managed.",
    )
    evaluation_periods = serializers.IntegerField(
        default=1,
        min_value=1,
        max_value=10,
        help_text="Metric alerts only: total check periods in the sliding evaluation window (M in N-of-M).",
    )
    datapoints_to_alarm = serializers.IntegerField(
        default=1,
        min_value=1,
        max_value=10,
        help_text="Metric alerts only: how many periods must breach to fire (N in N-of-M).",
    )
    cooldown_minutes = serializers.IntegerField(
        default=0,
        min_value=0,
        help_text="Metric alerts only: minimum minutes between repeated notifications. 0 means no cooldown.",
    )
    schedule_restriction = ScheduleRestrictionField(
        required=False,
        allow_null=True,
        help_text="Blocked local time windows when the alert must not notify. Times use the project timezone. Null disables quiet hours.",
    )
    snooze_until = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="ISO 8601 timestamp until which the alert is snoozed. Set to null to unsnooze.",
    )
    next_check_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the next evaluation is scheduled. Server-managed."
    )
    last_notified_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the last notification was sent. Server-managed."
    )
    last_checked_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the alert was last evaluated. Server-managed."
    )
    consecutive_failures = serializers.IntegerField(
        read_only=True, help_text="Consecutive evaluation failures. Resets on success. Server-managed."
    )
    first_enabled_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the alert was first enabled. Null means still a draft."
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the alert was created.")
    created_by = UserBasicSerializer(read_only=True)
    updated_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the alert was last modified."
    )

    class Meta:
        model = VisionAlertConfiguration
        fields = [
            "id",
            "scanner_id",
            "name",
            "enabled",
            "kind",
            "selection",
            "metric",
            "direction",
            "threshold",
            "window_days",
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
            "first_enabled_at",
            "created_at",
            "created_by",
            "updated_at",
        ]

    def validate_name(self, value: str) -> str:
        return value.strip() or "Untitled alert"

    def validate(self, attrs: dict) -> dict:
        instance = self.instance
        kind = attrs.get("kind", getattr(instance, "kind", None))

        if instance is not None:
            if "kind" in attrs and attrs["kind"] != instance.kind:
                raise ValidationError({"kind": "Cannot change the kind of an existing alert."})
            if "scanner" in attrs and attrs["scanner"].id != instance.scanner_id:
                raise ValidationError({"scanner_id": "Cannot move an alert to a different scanner."})

        name = attrs.get("name", getattr(instance, "name", None))
        if name:
            existing = VisionAlertConfiguration.objects.for_team(self.context["team_id"]).filter(name=name)
            if instance is not None:
                existing = existing.exclude(id=instance.id)
            if existing.exists():
                raise ValidationError({"name": "An alert with this name already exists."})

        view = self.context.get("view")
        scanner_for_access = attrs.get("scanner") if instance is None else getattr(instance, "scanner", None)
        if view is not None and scanner_for_access is not None:
            # Alerts inherit access from their scanner; a per-scanner grant must gate them.
            if not view.user_access_control.check_access_level_for_object(scanner_for_access, "editor"):
                raise PermissionDenied("You don't have access to this scanner.")

        if kind == VisionAlertKind.METRIC:
            threshold = attrs.get("threshold", getattr(instance, "threshold", None))
            if threshold is None:
                raise ValidationError({"threshold": "Metric alerts require a threshold."})
            window = attrs.get("window_days", getattr(instance, "window_days", 1))
            if window not in ALERT_WINDOW_DAYS:
                raise ValidationError({"window_days": f"Must be one of {list(ALERT_WINDOW_DAYS)}."})
            metric = attrs.get("metric", getattr(instance, "metric", VisionAlertMetric.COUNT))
            scanner = attrs.get("scanner", getattr(instance, "scanner", None))
            if metric == VisionAlertMetric.AVG_SCORE and scanner is not None:
                if scanner.scanner_type != ScannerType.SCORER:
                    raise ValidationError({"metric": "avg_score is only available on scorer scanners."})
        else:
            if attrs.get("threshold") is not None:
                raise ValidationError({"threshold": "Match alerts do not take a threshold."})
            metric_only = (
                "metric",
                "direction",
                "window_days",
                "check_interval_minutes",
                "evaluation_periods",
                "datapoints_to_alarm",
                "cooldown_minutes",
            )
            provided = [f for f in metric_only if f in (self.initial_data or {})]
            if provided:
                raise ValidationError({provided[0]: "Only metric alerts take this field."})

        evaluation_periods = attrs.get("evaluation_periods", getattr(instance, "evaluation_periods", 1))
        datapoints_to_alarm = attrs.get("datapoints_to_alarm", getattr(instance, "datapoints_to_alarm", 1))
        if datapoints_to_alarm > evaluation_periods:
            raise ValidationError({"datapoints_to_alarm": "Cannot exceed evaluation_periods."})

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

    def update(self, instance: VisionAlertConfiguration, validated_data: dict) -> VisionAlertConfiguration:
        snooze_data = validated_data.pop("snooze_until", _SENTINEL)

        threshold_fields = {
            "threshold",
            "direction",
            "metric",
            "selection",
            "datapoints_to_alarm",
            "evaluation_periods",
        }
        threshold_changed = _any_field_changed(instance, validated_data, threshold_fields)
        window_changed = _any_field_changed(instance, validated_data, {"window_days", "check_interval_minutes"})
        schedule_restriction_changed = _any_field_changed(instance, validated_data, {"schedule_restriction"})

        enabled_change: bool | None = None
        if "enabled" in validated_data and validated_data["enabled"] != instance.enabled:
            enabled_change = validated_data["enabled"]

        # One transaction wraps the state-machine transition, its VisionAlertEvent audit
        # row, and the save, so a failure can't orphan either side.
        with transaction.atomic():
            # Priority order: enable/disable wins over snooze, which wins over
            # threshold/selection changes. apply_outcome is the single writer of
            # state/consecutive_failures; match alerts route through it too so control-plane
            # actions land in the audit trail (their outcomes always resolve to not_firing).
            snapshot = instance.to_snapshot()
            if enabled_change is True:
                if instance.first_enabled_at is None:
                    validated_data.setdefault("first_enabled_at", timezone.now())
                apply_outcome(instance, apply_enable(snapshot), kind=VisionAlertEvent.Kind.ENABLE)
            elif enabled_change is False:
                apply_outcome(instance, apply_disable(snapshot), kind=VisionAlertEvent.Kind.DISABLE)
            elif snooze_data is not _SENTINEL:
                snooze_kind = VisionAlertEvent.Kind.UNSNOOZE if snooze_data is None else VisionAlertEvent.Kind.SNOOZE
                if instance.kind == VisionAlertKind.MATCH:
                    # Match alerts are stateless (DB-enforced); the drain honors snooze_until directly.
                    VisionAlertEvent.objects.create(
                        alert=instance,
                        kind=snooze_kind,
                        threshold_breached=False,
                        state_before=instance.state,
                        state_after=instance.state,
                    )
                elif snooze_data is None:
                    apply_outcome(instance, apply_unsnooze(snapshot), kind=snooze_kind)
                else:
                    apply_outcome(instance, apply_snooze(snapshot), kind=snooze_kind)
            elif threshold_changed:
                apply_outcome(instance, apply_threshold_change(snapshot), kind=VisionAlertEvent.Kind.THRESHOLD_CHANGE)

            if snooze_data is not _SENTINEL:
                instance.snooze_until = snooze_data

            if instance.kind == VisionAlertKind.METRIC and (
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

    def create(self, validated_data: dict) -> VisionAlertConfiguration:
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user

        if validated_data.get("enabled", True):
            validated_data["first_enabled_at"] = timezone.now()

        with transaction.atomic():
            # Locking the team row serialises concurrent creates for this team so the
            # per-team cap can't be raced past.
            team = Team.objects.select_for_update().get(id=validated_data["team_id"])
            if validated_data["team_id"] not in UNCAPPED_ALERT_TEAM_IDS:
                count = VisionAlertConfiguration.objects.for_team(validated_data["team_id"]).count()
                if count >= MAX_ALERTS_PER_TEAM:
                    raise ValidationError(f"Maximum number of alerts ({MAX_ALERTS_PER_TEAM}) reached for this team.")
            # The drain, not the scheduler, drives match alerts; only metric alerts get a schedule.
            if validated_data.get("kind") != VisionAlertKind.MATCH and (
                schedule_restriction := validated_data.get("schedule_restriction")
            ):
                validated_data["next_check_at"] = next_allowed_check_at(
                    datetime.now(UTC),
                    team_timezone=team.timezone,
                    schedule_restriction=schedule_restriction,
                )
            return super().create(validated_data)


class VisionAlertEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = VisionAlertEvent
        fields = [
            "id",
            "created_at",
            "kind",
            "state_before",
            "state_after",
            "threshold_breached",
            "metric_value",
            "error_message",
        ]
        read_only_fields = fields


class VisionAlertListQuerySerializer(serializers.Serializer):
    scanner_id = serializers.UUIDField(
        required=False,
        help_text="Only return alerts on this scanner.",
    )


class VisionAlertCreateDestinationSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=VISION_DESTINATION_TYPES, help_text="Notification destination type.")
    slack_workspace_id = serializers.IntegerField(
        required=False, help_text="Integration ID for the Slack workspace. Required when type=slack."
    )
    slack_channel_id = serializers.CharField(required=False, help_text="Slack channel ID. Required when type=slack.")
    slack_channel_name = serializers.CharField(
        required=False, allow_blank=True, help_text="Human-readable channel name for display."
    )
    webhook_url = serializers.URLField(
        required=False, help_text="HTTPS endpoint to post to. Required when type=webhook."
    )

    def validate_webhook_url(self, value: str) -> str:
        if not value.startswith("https://"):
            raise ValidationError("Webhook URLs must use https.")
        return value

    def validate(self, attrs: dict) -> dict:
        data = cast(AlertDestinationData, attrs)
        data["type"] = DestinationType(attrs["type"])
        try:
            validate_destination_data(data, allowed_destination_types=VISION_DESTINATION_TYPES)
        except AlertDestinationValidationError as error:
            if error.field:
                raise ValidationError({error.field: error.message})
            raise ValidationError(error.message)
        return attrs


class VisionAlertDeleteDestinationSerializer(serializers.Serializer):
    hog_function_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=len(VISION_ALERT_EVENT_IDS),
        help_text="HogFunction IDs to delete as one atomic destination group.",
    )


class VisionAlertDestinationResponseSerializer(serializers.Serializer):
    hog_function_ids = serializers.ListField(
        child=serializers.UUIDField(), help_text="HogFunctions backing the created destination, one per event kind."
    )


@extend_schema_view(list=extend_schema(parameters=[VisionAlertListQuerySerializer]))
class VisionAlertViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "vision_alert"
    scope_object_read_actions = ["list", "retrieve", "events"]
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "destroy",
        "create_destination",
        "delete_destination",
        "reset",
    ]
    # `objects` is fail-closed; `safely_get_queryset` re-scopes to the request team.
    queryset = VisionAlertConfiguration.objects.unscoped().order_by("-created_at")
    serializer_class = VisionAlertConfigurationSerializer
    lookup_field = "id"

    # Configuring an alert or its destinations routes recording-derived content off-platform,
    # so it needs the same session-recording read gate as vision actions.
    _CONFIG_ACTIONS = {"create", "update", "partial_update", "create_destination"}

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        if self.action in self._CONFIG_ACTIONS:
            return ["vision_alert:write", "session_recording:read"]
        return None

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if self.action in self._CONFIG_ACTIONS and not self.user_access_control.check_access_level_for_resource(
            "session_recording", required_level="viewer"
        ):
            raise PermissionDenied("Configuring a Replay Vision alert requires session_recording read access.")

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        if self.action == "list":
            query_serializer = VisionAlertListQuerySerializer(data=self.request.query_params)
            query_serializer.is_valid(raise_exception=True)
            scanner_id = query_serializer.validated_data.get("scanner_id")
            if scanner_id:
                queryset = queryset.filter(scanner_id=scanner_id)
            # Alerts carry no object-level rows of their own; a scanner-level restriction
            # must hide that scanner's alerts from the list.
            accessible_scanners = self.user_access_control.filter_queryset_by_access_level(
                ReplayScanner.objects.filter(team_id=self.team_id)
            )
            queryset = queryset.filter(scanner_id__in=accessible_scanners.values_list("id", flat=True))
        return queryset.filter(team_id=self.team_id).select_related("created_by", "scanner")

    def safely_get_object(self, queryset: QuerySet) -> VisionAlertConfiguration:
        alert = get_object_or_404(
            queryset, **{self.lookup_field: self.kwargs[self.lookup_url_kwarg or self.lookup_field]}
        )
        self._check_scanner_access(alert)
        return alert

    def _check_scanner_access(self, alert: VisionAlertConfiguration) -> None:
        # Object-level access rows live on the scanner, not the alert; the generic
        # object check cannot see them, so check the scanner explicitly.
        self.check_object_permissions(self.request, alert.scanner)

    def _get_locked_alert(self) -> VisionAlertConfiguration:
        # No select_related here: FOR UPDATE rejects the outer join a nullable created_by adds.
        queryset = VisionAlertConfiguration.objects.for_team(self.team_id).select_for_update()
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        alert = get_object_or_404(queryset, **{self.lookup_field: self.kwargs[lookup_url_kwarg]})
        self.check_object_permissions(self.request, alert)
        self._check_scanner_access(alert)
        return alert

    def update(self, request: Request, *args: object, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        with transaction.atomic():
            instance = self._get_locked_alert()
            serializer = self.get_serializer(instance, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)
        return Response(serializer.data)

    def _event_kinds_for(self, alert: VisionAlertConfiguration) -> tuple[EventKind, ...]:
        return MATCH_EVENT_KINDS if alert.kind == VisionAlertKind.MATCH else METRIC_EVENT_KINDS

    @extend_schema(
        request=VisionAlertCreateDestinationSerializer,
        responses={201: VisionAlertDestinationResponseSerializer},
        description="Create a notification destination for this alert. One HogFunction is created per alert event kind atomically.",
    )
    @action(detail=True, methods=["POST"], url_path="destinations", required_scopes=["vision_alert:write"])
    def create_destination(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = VisionAlertCreateDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = cast(AlertDestinationData, serializer.validated_data)

        with transaction.atomic():
            alert = self._get_locked_alert()
            existing = count_active_alert_destinations(
                team_id=self.team_id, alert_id=str(alert.id), allowed_event_ids=VISION_ALERT_EVENT_IDS
            )
            event_kinds = self._event_kinds_for(alert)
            if existing + len(event_kinds) > MAX_DESTINATIONS_PER_ALERT * len(event_kinds):
                raise ValidationError(
                    f"Maximum number of destinations ({MAX_DESTINATIONS_PER_ALERT}) reached for this alert."
                )
            configs = [
                build_alert_destination_config(
                    team=alert.team,
                    spec=EVENT_KIND_CONFIG[kind],
                    alert_id=str(alert.id),
                    alert_name=alert.name,
                    data=data,
                    slack_context_elements=VISION_ALERT_SLACK_CONTEXT_ELEMENTS,
                )
                for kind in event_kinds
            ]
            hog_functions = create_alert_destination_hog_functions(
                configs,
                request=self.request,
                alert_id=str(alert.id),
                allowed_event_ids=VISION_ALERT_EVENT_IDS,
            )

        report_user_action(
            request.user,
            "replay vision alert destination created",
            {"alert_id": str(alert.id), "type": data["type"], "event_kinds": list(event_kinds)},
            request=request,
        )
        response = VisionAlertDestinationResponseSerializer({"hog_function_ids": [hf.id for hf in hog_functions]})
        return Response(response.data, status=201)

    @extend_schema(
        request=VisionAlertDeleteDestinationSerializer,
        responses={204: None},
        description="Delete a notification destination by deleting its HogFunction group atomically.",
    )
    @action(detail=True, methods=["POST"], url_path="destinations/delete", required_scopes=["vision_alert:write"])
    def delete_destination(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = VisionAlertDeleteDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hog_function_ids = serializer.validated_data["hog_function_ids"]

        with transaction.atomic():
            alert = self._get_locked_alert()
            soft_delete_alert_destinations(
                team_id=self.team_id,
                alert_id=str(alert.id),
                allowed_event_ids=VISION_ALERT_EVENT_IDS,
                hog_function_ids=hog_function_ids,
            )

        report_user_action(
            request.user,
            "replay vision alert destination deleted",
            {"alert_id": str(alert.id), "count": len(hog_function_ids)},
            request=request,
        )
        return Response(status=204)

    @extend_schema(
        request=None,
        parameters=[
            OpenApiParameter(
                name="kind",
                type=str,
                enum=VisionAlertEvent.Kind.values,
                required=False,
                description="Narrow the history to one event kind.",
            )
        ],
        responses={200: VisionAlertEventSerializer(many=True)},
        description=(
            "Paginated event history for this alert, newest first. Quiet no-op check rows "
            "(no state change, no error) are filtered out. Optional `?kind=...` narrows to one kind."
        ),
    )
    @action(detail=True, methods=["GET"], url_path="events", required_scopes=["vision_alert:read"])
    def events(self, request: Request, *args: object, **kwargs: object) -> Response:
        alert = self.get_object()
        queryset = (
            VisionAlertEvent.objects.filter(alert=alert)
            .filter(
                ~Q(kind=VisionAlertEvent.Kind.CHECK)
                | Q(error_message__isnull=False)
                | ~Q(state_before=F("state_after"))
            )
            .order_by("-created_at")
        )

        kind = request.query_params.get("kind")
        if kind is not None:
            valid_kinds = VisionAlertEvent.Kind.values
            if kind not in valid_kinds:
                raise ValidationError({"kind": f"Must be one of {sorted(valid_kinds)}."})
            queryset = queryset.filter(kind=kind)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = VisionAlertEventSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = VisionAlertEventSerializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(
        request=None,
        responses={200: VisionAlertConfigurationSerializer},
        description="Reset a broken alert. Clears the consecutive-failure counter and schedules an immediate recheck.",
    )
    @action(detail=True, methods=["POST"], url_path="reset", required_scopes=["vision_alert:write"])
    def reset(self, request: Request, *args: object, **kwargs: object) -> Response:
        with transaction.atomic():
            alert = self._get_locked_alert()
            try:
                outcome = apply_user_reset(alert.to_snapshot())
            except InvalidTransition:
                raise ValidationError({"state": "Only broken alerts can be reset."})
            update_fields = apply_outcome(alert, outcome, kind=VisionAlertEvent.Kind.RESET)
            update_fields.extend(alert.clear_next_check())
            alert.save(update_fields=update_fields)
        report_user_action(request.user, "replay vision alert reset", {"alert_id": str(alert.id)}, request=request)
        serializer = self.get_serializer(alert)
        return Response(serializer.data)

    def destroy(self, request: Request, *args: object, **kwargs: Any) -> Response:
        # The lock serialises against create_destination, which would otherwise insert
        # HogFunctions after the cleanup pass and orphan them.
        with transaction.atomic():
            instance = self._get_locked_alert()
            self.perform_destroy(instance)
        return Response(status=204)

    def perform_destroy(self, instance: VisionAlertConfiguration) -> None:
        soft_delete_all_alert_destinations(
            team_id=self.team_id,
            alert_id=str(instance.id),
            allowed_event_ids=VISION_ALERT_EVENT_IDS,
        )
        instance.delete()
