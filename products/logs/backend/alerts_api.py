import datetime as dt
from datetime import UTC, datetime
from typing import Final, cast
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import OuterRef, QuerySet, Subquery

from drf_spectacular.utils import extend_schema, extend_schema_field
from loginas.utils import is_impersonated_session
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.hog_function import HogFunctionSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models.activity_logging.activity_log import Change, Detail, changes_between, log_activity
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.utils import relative_date_parse

from products.logs.backend.alert_check_query import AlertCheckQuery, BucketedCount
from products.logs.backend.alert_destinations import EVENT_KINDS, EventKind, build_slack_config, build_webhook_config
from products.logs.backend.alert_state_machine import (
    AlertCheckOutcome,
    AlertSnapshot,
    AlertState,
    CheckResult,
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
from products.logs.backend.models import MAX_EVALUATION_PERIODS, LogsAlertConfiguration, LogsAlertEvent

ALLOWED_WINDOW_MINUTES = {1, 5, 10, 15, 30, 60}
MAX_ALERTS_PER_TEAM = 20
MAX_SIMULATE_LOOKBACK_DAYS = 30
MAX_SIMULATE_BUCKETS = 15_000
_SENTINEL: Final = object()
_NOT_ANNOTATED: Final = object()


def _any_field_changed(instance: LogsAlertConfiguration, validated_data: dict, fields: set[str]) -> bool:
    return any(f in validated_data and validated_data[f] != getattr(instance, f) for f in fields)


class LogsAlertConfigurationSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    filters = serializers.JSONField(
        help_text="Filter criteria — subset of LogsViewerFilters. Must contain at least one of: "
        "severityLevels (list of severity strings), serviceNames (list of service name strings), "
        "or filterGroup (property filter group object)."
    )
    threshold_operator = serializers.ChoiceField(
        choices=LogsAlertConfiguration.ThresholdOperator.choices,
        default=LogsAlertConfiguration.ThresholdOperator.ABOVE,
        help_text="Whether the alert fires when the count is above or below the threshold.",
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
    last_error_message = serializers.SerializerMethodField(
        help_text=(
            "Error message from the most recent errored check, or null if the alert's "
            "most recent check was successful. Sourced from LogsAlertEvent without "
            "denormalization so retention-aware cleanup rules stay the only source of truth."
        ),
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
            LogsAlertEvent.objects.filter(alert=obj, error_message__isnull=False)
            .order_by("-created_at")
            .values_list("error_message", flat=True)
            .first()
        )

    class Meta:
        model = LogsAlertConfiguration
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
            "snooze_until",
            "next_check_at",
            "last_notified_at",
            "last_checked_at",
            "consecutive_failures",
            "last_error_message",
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
            "created_at",
            "created_by",
            "updated_at",
        ]

    def validate(self, attrs: dict) -> dict:
        filters = attrs.get("filters", getattr(self.instance, "filters", None) or {})
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

        return attrs

    def update(self, instance: LogsAlertConfiguration, validated_data: dict) -> LogsAlertConfiguration:
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

        enabled_change: bool | None = None
        if "enabled" in validated_data and validated_data["enabled"] != instance.enabled:
            enabled_change = validated_data["enabled"]

        # Resolve the state-machine transition in priority order: enable/disable wins over
        # snooze, which wins over threshold/filter changes. Window-only edits don't touch
        # state at all. All transitions return an Outcome; apply_outcome is the single
        # place that actually writes to `state`/`consecutive_failures`.
        snapshot = instance.to_snapshot()
        if enabled_change is True:
            apply_outcome(instance, apply_enable(snapshot))
        elif enabled_change is False:
            apply_outcome(instance, apply_disable(snapshot))
        elif snooze_data is not _SENTINEL:
            if snooze_data is None:
                apply_outcome(instance, apply_unsnooze(snapshot))
            else:
                apply_outcome(instance, apply_snooze(snapshot))
        elif threshold_changed:
            apply_outcome(instance, apply_threshold_change(snapshot))

        # snooze_until is a timestamp column, not a state — carry it alongside the state
        # transition so the serializer's single save persists both.
        if snooze_data is not _SENTINEL:
            instance.snooze_until = snooze_data

        if threshold_changed or window_changed:
            instance.clear_next_check()

        return super().update(instance, validated_data)

    def create(self, validated_data: dict) -> LogsAlertConfiguration:
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user

        with transaction.atomic():
            # select_for_update().count() doesn't acquire row locks because
            # Django optimises count() to SELECT COUNT(*). Locking the team
            # row instead serialises concurrent creates for this team.
            Team.objects.select_for_update().get(id=validated_data["team_id"])
            count = LogsAlertConfiguration.objects.filter(team_id=validated_data["team_id"]).count()
            if count >= MAX_ALERTS_PER_TEAM:
                raise ValidationError(f"Maximum number of alerts ({MAX_ALERTS_PER_TEAM}) reached for this team.")
            return super().create(validated_data)


def _validate_filters(filters: dict) -> None:
    """Shared filter validation for both create/update and simulate."""
    if not isinstance(filters, dict):
        raise ValidationError({"filters": "Must be a JSON object."})
    has_severity = bool(filters.get("severityLevels"))
    has_services = bool(filters.get("serviceNames"))
    has_filter_group = bool(filters.get("filterGroup"))
    if not (has_severity or has_services or has_filter_group):
        raise ValidationError(
            {"filters": "At least one filter is required (severityLevels, serviceNames, or filterGroup)."}
        )


class LogsAlertSimulateBucketSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField(help_text="Bucket start timestamp.")
    count = serializers.IntegerField(help_text="Number of matching logs in this bucket.")
    threshold_breached = serializers.BooleanField(help_text="Whether the count crossed the threshold in this bucket.")
    state = serializers.CharField(help_text="Alert state after evaluating this bucket.")
    notification = serializers.CharField(help_text="Notification action: none, fire, or resolve.")
    reason = serializers.CharField(help_text="Human-readable explanation of the state transition.")


class LogsAlertSimulateRequestSerializer(serializers.Serializer):
    filters = serializers.JSONField(help_text="Filter criteria — same format as LogsAlertConfiguration.filters.")
    threshold_count = serializers.IntegerField(
        min_value=1,
        help_text="Threshold count to evaluate against.",
    )
    threshold_operator = serializers.ChoiceField(
        choices=LogsAlertConfiguration.ThresholdOperator.choices,
        help_text="Whether the alert fires when the count is above or below the threshold.",
    )
    window_minutes = serializers.IntegerField(
        help_text="Window size in minutes — determines bucket interval.",
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
        help_text="Minutes to wait after firing before sending another notification.",
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
    type = serializers.ChoiceField(choices=["slack", "webhook"], help_text="Destination type — slack or webhook.")
    slack_workspace_id = serializers.IntegerField(
        required=False, help_text="Integration ID for the Slack workspace. Required when type=slack."
    )
    slack_channel_id = serializers.CharField(required=False, help_text="Slack channel ID. Required when type=slack.")
    slack_channel_name = serializers.CharField(
        required=False, allow_blank=True, help_text="Human-readable channel name for display."
    )
    webhook_url = serializers.URLField(
        required=False, help_text="HTTPS endpoint to POST to. Required when type=webhook."
    )

    def validate(self, attrs: dict) -> dict:
        destination_type = attrs["type"]
        if destination_type == "slack":
            if not attrs.get("slack_workspace_id") or not attrs.get("slack_channel_id"):
                raise ValidationError("slack_workspace_id and slack_channel_id are required for slack destinations.")
        elif destination_type == "webhook":
            if not attrs.get("webhook_url"):
                raise ValidationError("webhook_url is required for webhook destinations.")
        return attrs


class LogsAlertDeleteDestinationSerializer(serializers.Serializer):
    hog_function_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        help_text="HogFunction IDs to delete as one atomic destination group.",
    )


class LogsAlertDestinationResponseSerializer(serializers.Serializer):
    hog_function_ids = serializers.ListField(child=serializers.UUIDField())


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


@extend_schema(tags=["logs"])
class LogsAlertViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "logs"
    queryset = LogsAlertConfiguration.objects.all().order_by("-created_at")
    serializer_class = LogsAlertConfigurationSerializer
    lookup_field = "id"
    posthog_feature_flag = "logs-alerting"
    permission_classes = [PostHogFeatureFlagPermission]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        # Correlated subquery so list/retrieve can surface `last_error_message` in a
        # single round-trip instead of one extra query per alert.
        latest_error = (
            LogsAlertEvent.objects.filter(alert=OuterRef("pk"), error_message__isnull=False)
            .order_by("-created_at")
            .values("error_message")[:1]
        )
        return queryset.filter(team_id=self.team_id).annotate(_latest_error_message=Subquery(latest_error))

    @extend_schema(
        request=LogsAlertCreateDestinationSerializer,
        responses={201: LogsAlertDestinationResponseSerializer},
        description="Create a notification destination for this alert. One HogFunction is created per alert event kind (firing, resolved, ...) atomically.",
    )
    @action(detail=True, methods=["POST"], url_path="destinations")
    def create_destination(self, request: Request, *args: object, **kwargs: object) -> Response:
        alert = self.get_object()
        serializer = LogsAlertCreateDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with transaction.atomic():
            hog_functions = [self._build_and_create_hog_function(alert, data, kind) for kind in EVENT_KINDS]

        report_user_action(
            request.user,
            "logs alert destination created",
            {"alert_id": str(alert.id), "type": data["type"], "event_kinds": list(EVENT_KINDS)},
        )
        response = LogsAlertDestinationResponseSerializer({"hog_function_ids": [hf.id for hf in hog_functions]})
        return Response(response.data, status=201)

    @extend_schema(
        request=LogsAlertDeleteDestinationSerializer,
        responses={204: None},
        description="Delete a notification destination by deleting its HogFunction group atomically.",
    )
    @action(detail=True, methods=["POST"], url_path="destinations/delete")
    def delete_destination(self, request: Request, *args: object, **kwargs: object) -> Response:
        alert = self.get_object()
        serializer = LogsAlertDeleteDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hog_function_ids = serializer.validated_data["hog_function_ids"]

        with transaction.atomic():
            updated = HogFunction.objects.filter(
                team_id=self.team_id,
                id__in=hog_function_ids,
                filters__properties__contains=[{"key": "alert_id", "value": str(alert.id)}],
            ).update(deleted=True)
            if updated != len(hog_function_ids):
                # Ownership check: if the filtered UPDATE touched fewer rows than we were asked
                # to delete, something in the list doesn't belong to this alert. Roll back.
                raise ValidationError("One or more HogFunctions do not belong to this alert.")

        report_user_action(
            request.user,
            "logs alert destination deleted",
            {"alert_id": str(alert.id), "count": len(hog_function_ids)},
        )
        return Response(status=204)

    def _build_and_create_hog_function(
        self,
        alert: LogsAlertConfiguration,
        data: dict,
        kind: EventKind,
    ) -> HogFunction:
        if data["type"] == "slack":
            config = build_slack_config(
                alert,
                kind,
                slack_workspace_id=data["slack_workspace_id"],
                slack_channel_id=data["slack_channel_id"],
                slack_channel_name=data.get("slack_channel_name"),
            )
        else:
            config = build_webhook_config(alert, kind, webhook_url=data["webhook_url"])

        # Route through HogFunctionSerializer so template lookup and bytecode compilation run.
        team = config.pop("team")
        serializer = HogFunctionSerializer(
            data=config,
            context={"request": self.request, "get_team": lambda: team, "is_create": True},
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save(team=team)

    @extend_schema(
        request=None,
        responses={200: LogsAlertConfigurationSerializer},
        description="Reset a broken alert. Clears the consecutive-failure counter and schedules an immediate recheck.",
    )
    @action(detail=True, methods=["POST"], url_path="reset")
    def reset(self, request: Request, *args: object, **kwargs: object) -> Response:
        alert = self.get_object()
        previous_failures = alert.consecutive_failures
        try:
            outcome = apply_user_reset(alert.to_snapshot())
        except InvalidTransition:
            raise ValidationError({"state": "Only broken alerts can be reset."})
        with transaction.atomic():
            update_fields = apply_outcome(alert, outcome)
            update_fields.extend(alert.clear_next_check())
            alert.save(update_fields=update_fields)
            # The model's auto-signal skips these fields (signal_exclusions silences
            # engine-driven churn) so we log the user-initiated reset explicitly.
            log_activity(
                organization_id=self.team.organization_id,
                team_id=self.team_id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated_session(request),
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
        report_user_action(request.user, "logs alert reset", {"alert_id": str(alert.id)})
        return Response(self.get_serializer(alert).data)

    @extend_schema(
        request=LogsAlertSimulateRequestSerializer,
        responses={200: LogsAlertSimulateResponseSerializer},
        description="Simulate a logs alert on historical data using the full state machine. "
        "Read-only — no alert check records are created.",
    )
    @action(detail=False, methods=["POST"], url_path="simulate")
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
        )

        sparse_buckets: list[BucketedCount] = AlertCheckQuery(
            team=self.team,
            alert=fake_alert,
            date_from=date_from_dt,
            date_to=date_to_dt,
        ).execute_bucketed(interval_minutes=1, limit=MAX_SIMULATE_BUCKETS)

        # Fill gaps so every minute has a count (0 if no logs)
        minute_buckets = _fill_empty_buckets(sparse_buckets, date_from_dt, date_to_dt, 1)

        # Compute rolling window sum: for each minute, sum the preceding window_minutes of counts.
        # This matches the real alerting cadence: check every minute, count logs in the last N minutes.
        counts = [b.count for b in minute_buckets]
        rolling_counts: list[int] = []
        for i in range(len(counts)):
            window_start = max(0, i - window_minutes + 1)
            rolling_counts.append(sum(counts[window_start : i + 1]))

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

        for i, bucket in enumerate(minute_buckets):
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

    def _track(self, event: str, instance: LogsAlertConfiguration) -> None:
        report_user_action(
            self.request.user,
            event,
            {
                "id": str(instance.id),
                "name": instance.name,
                "enabled": instance.enabled,
                "threshold_count": instance.threshold_count,
                "threshold_operator": instance.threshold_operator,
                "window_minutes": instance.window_minutes,
            },
            team=self.team,
            request=self.request,
        )

    def perform_create(self, serializer) -> None:
        self._track("logs alert created", serializer.save())

    def perform_update(self, serializer) -> None:
        self._track("logs alert updated", serializer.save())

    def perform_destroy(self, instance: LogsAlertConfiguration) -> None:
        self._track("logs alert deleted", instance)
        super().perform_destroy(instance)


@mutable_receiver(model_activity_signal, sender=LogsAlertConfiguration)
def handle_logs_alert_activity(
    sender,
    scope,
    before_update,
    after_update,
    activity,
    user,
    was_impersonated=False,
    **kwargs,
):
    instance = after_update or before_update
    log_activity(
        organization_id=instance.team.organization_id,
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=instance.name,
        ),
    )
