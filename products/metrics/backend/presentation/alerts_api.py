"""CRUD + history API for metrics alerts."""

from __future__ import annotations

from typing import Any, Final, cast

from django.db import transaction

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.permissions import PostHogFeatureFlagPermission

from products.alerts.backend.destination_configs import (
    AlertDestinationData,
    build_alert_destination_config,
    validate_destination_data,
)
from products.alerts.backend.destinations import (
    create_alert_destination_hog_functions,
    list_alert_destination_groups,
    soft_delete_alert_destinations,
    soft_delete_all_alert_destinations,
)
from products.metrics.backend.facade.alerts import (
    EVENT_KIND_CONFIG,
    EVENT_KINDS,
    METRICS_ALERT_EVENT_IDS,
    METRICS_ALERT_SLACK_CONTEXT_ELEMENTS,
    METRICS_DESTINATION_TYPES,
    apply_disable,
    apply_enable,
    apply_outcome,
    apply_snooze,
    apply_threshold_change,
    apply_unsnooze,
)
from products.metrics.backend.facade.contracts import METRICS_FEATURE_FLAG
from products.metrics.backend.facade.models import MetricsAlertConfiguration, MetricsAlertEvent

MAX_DESTINATION_IDS_PER_DELETE_REQUEST = 50

_SENTINEL: Final = object()

# Fields whose change re-evaluates the alert from scratch (threshold / window shape).
_THRESHOLD_FIELDS = {
    "threshold_value",
    "threshold_operator",
    "evaluation_periods",
    "datapoints_to_alarm",
    "filters",
    "group_by",
    "aggregation",
    "metric_name",
    "quantile",
}


def _any_field_changed(instance: MetricsAlertConfiguration, validated_data: dict, fields: set[str]) -> bool:
    return any(f in validated_data and validated_data[f] != getattr(instance, f) for f in fields)


class MetricsAlertDestinationSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=[(d.value, d.label) for d in METRICS_DESTINATION_TYPES])
    slack_workspace_id = serializers.IntegerField(required=False)
    slack_channel_id = serializers.CharField(required=False)
    slack_channel_name = serializers.CharField(required=False)
    webhook_url = serializers.CharField(required=False)

    def validate(self, data: dict) -> dict:
        try:
            validate_destination_data(
                cast(AlertDestinationData, data), allowed_destination_types=METRICS_DESTINATION_TYPES
            )
        except Exception as e:
            raise ValidationError(getattr(e, "message", str(e)))
        return data


class MetricsAlertDeleteDestinationSerializer(serializers.Serializer):
    hog_function_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)


class MetricsAlertDestinationResponseSerializer(serializers.Serializer):
    hog_function_ids = serializers.ListField(child=serializers.UUIDField())


class MetricsAlertConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = MetricsAlertConfiguration
        fields = [
            "id",
            "name",
            "enabled",
            "metric_name",
            "aggregation",
            "quantile",
            "filters",
            "group_by",
            "threshold_value",
            "threshold_operator",
            "window_minutes",
            "check_interval_minutes",
            "evaluation_periods",
            "datapoints_to_alarm",
            "cooldown_minutes",
            "snooze_until",
            "schedule_restriction",
            "state",
            "consecutive_failures",
            "next_check_at",
            "last_notified_at",
            "last_checked_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "state",
            "consecutive_failures",
            "next_check_at",
            "last_notified_at",
            "last_checked_at",
            "created_at",
        ]

    def validate(self, data: dict) -> dict:
        evaluation_periods = data.get(
            "evaluation_periods", getattr(self.instance, "evaluation_periods", 1) if self.instance else 1
        )
        datapoints_to_alarm = data.get(
            "datapoints_to_alarm", getattr(self.instance, "datapoints_to_alarm", 1) if self.instance else 1
        )
        if datapoints_to_alarm > evaluation_periods:
            raise ValidationError({"datapoints_to_alarm": "cannot exceed evaluation_periods"})
        aggregation = data.get("aggregation", getattr(self.instance, "aggregation", None) if self.instance else None)
        if aggregation in ("quantile", "histogram_quantile"):
            quantile = data.get("quantile", getattr(self.instance, "quantile", None) if self.instance else None)
            if quantile is None or not 0.0 < quantile < 1.0:
                raise ValidationError({"quantile": "quantile-based aggregations require a quantile in (0, 1)"})
        return data

    def create(self, validated_data: dict) -> MetricsAlertConfiguration:
        return MetricsAlertConfiguration.objects.create(**validated_data)

    def update(self, instance: MetricsAlertConfiguration, validated_data: dict) -> MetricsAlertConfiguration:
        snooze_data = validated_data.pop("snooze_until", _SENTINEL)

        threshold_changed = _any_field_changed(instance, validated_data, _THRESHOLD_FIELDS)
        schedule_changed = _any_field_changed(instance, validated_data, {"check_interval_minutes", "window_minutes"})

        enabled_change: bool | None = None
        if "enabled" in validated_data and validated_data["enabled"] != instance.enabled:
            enabled_change = validated_data["enabled"]

        # Route the edit through the shared state machine so lifecycle fields (state,
        # consecutive_failures) stay consistent and every transition is audited.
        # Priority: enable/disable > snooze > threshold. Window/interval-only edits
        # leave state untouched. apply_outcome is the single writer of state fields.
        with transaction.atomic():
            snapshot = instance.to_snapshot()
            if enabled_change is True:
                apply_outcome(instance, apply_enable(snapshot), kind=MetricsAlertEvent.Kind.ENABLE)
            elif enabled_change is False:
                apply_outcome(instance, apply_disable(snapshot), kind=MetricsAlertEvent.Kind.DISABLE)
            elif snooze_data is not _SENTINEL:
                if snooze_data is None:
                    apply_outcome(instance, apply_unsnooze(snapshot), kind=MetricsAlertEvent.Kind.UNSNOOZE)
                else:
                    apply_outcome(instance, apply_snooze(snapshot), kind=MetricsAlertEvent.Kind.SNOOZE)
            elif threshold_changed:
                apply_outcome(instance, apply_threshold_change(snapshot), kind=MetricsAlertEvent.Kind.THRESHOLD_CHANGE)

            # snooze_until is a timestamp column, carried alongside the state transition
            # so the single save persists both.
            if snooze_data is not _SENTINEL:
                instance.snooze_until = snooze_data

            # Any evaluation-affecting change re-evaluates from scratch: clear
            # next_check_at so the scheduler picks the alert up on the next tick.
            if enabled_change is True or threshold_changed or schedule_changed:
                validated_data["next_check_at"] = None

            return super().update(instance, validated_data)


class MetricsAlertConfigurationDetailSerializer(MetricsAlertConfigurationSerializer):
    destinations = serializers.SerializerMethodField()

    class Meta(MetricsAlertConfigurationSerializer.Meta):
        fields = [*MetricsAlertConfigurationSerializer.Meta.fields, "destinations"]

    def get_destinations(self, obj: MetricsAlertConfiguration) -> list[dict[str, Any]]:
        groups = list_alert_destination_groups(
            team_id=obj.team_id,
            alert_id=str(obj.id),
            allowed_event_ids=METRICS_ALERT_EVENT_IDS,
        )
        return [
            {
                "hog_function_ids": [str(i) for i in group.hog_function_ids],
                "name": group.name,
            }
            for group in groups
        ]


class MetricsAlertEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = MetricsAlertEvent
        fields = [
            "id",
            "kind",
            "value",
            "threshold_breached",
            "labels",
            "state_before",
            "state_after",
            "error_message",
            "query_duration_ms",
            "created_at",
        ]


@extend_schema(tags=["metrics"])
class MetricsAlertViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "metrics"
    queryset = MetricsAlertConfiguration.objects.all()
    serializer_class = MetricsAlertConfigurationSerializer
    # Same private-alpha gate as the rest of metrics.
    posthog_feature_flag = METRICS_FEATURE_FLAG
    permission_classes = [PostHogFeatureFlagPermission]

    def get_serializer_class(self) -> type[serializers.ModelSerializer]:
        if self.action == "retrieve":
            return MetricsAlertConfigurationDetailSerializer
        return MetricsAlertConfigurationSerializer

    def safely_get_queryset(self, queryset: Any) -> Any:
        return MetricsAlertConfiguration.objects.filter(team_id=self.team_id).order_by("-created_at")

    def _get_locked_alert(self) -> MetricsAlertConfiguration:
        return MetricsAlertConfiguration.objects.select_for_update().get(id=self.kwargs["pk"], team_id=self.team_id)

    def perform_create(self, serializer: serializers.ModelSerializer) -> None:
        serializer.save(team=self.team)
        report_user_action(
            self.request.user,
            "metrics alert created",
            {"alert_id": str(serializer.instance.id)},
            team=self.team,
            request=self.request,
        )

    def perform_destroy(self, instance: MetricsAlertConfiguration) -> None:
        soft_delete_all_alert_destinations(
            team_id=self.team_id,
            alert_id=str(instance.id),
            allowed_event_ids=METRICS_ALERT_EVENT_IDS,
        )
        instance.delete()

    @extend_schema(
        request=MetricsAlertDestinationSerializer, responses={201: MetricsAlertDestinationResponseSerializer}
    )
    @action(detail=True, methods=["POST"], url_path="destinations", required_scopes=["metrics:write"])
    def create_destination(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = MetricsAlertDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = cast(AlertDestinationData, serializer.validated_data)

        with transaction.atomic():
            alert = self._get_locked_alert()
            configs = [
                build_alert_destination_config(
                    team=alert.team,
                    spec=EVENT_KIND_CONFIG[kind],
                    alert_id=str(alert.id),
                    alert_name=alert.name,
                    data=data,
                    slack_context_elements=METRICS_ALERT_SLACK_CONTEXT_ELEMENTS,
                )
                for kind in EVENT_KINDS
            ]
            hog_functions = create_alert_destination_hog_functions(
                configs,
                request=self.request,
                alert_id=str(alert.id),
                allowed_event_ids=METRICS_ALERT_EVENT_IDS,
            )

        report_user_action(
            request.user,
            "metrics alert destination created",
            {"alert_id": str(alert.id), "type": data["type"], "event_kinds": list(EVENT_KINDS)},
            request=request,
        )
        response = MetricsAlertDestinationResponseSerializer({"hog_function_ids": [hf.id for hf in hog_functions]})
        return Response(response.data, status=201)

    @extend_schema(request=MetricsAlertDeleteDestinationSerializer, responses={204: None})
    @action(detail=True, methods=["POST"], url_path="destinations/delete", required_scopes=["metrics:write"])
    def delete_destination(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = MetricsAlertDeleteDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hog_function_ids = serializer.validated_data["hog_function_ids"]

        with transaction.atomic():
            alert = self._get_locked_alert()
            groups = list_alert_destination_groups(
                team_id=self.team_id,
                alert_id=str(alert.id),
                allowed_event_ids=METRICS_ALERT_EVENT_IDS,
            )
            largest_server_group = max((len(group.hog_function_ids) for group in groups), default=0)
            if len(hog_function_ids) > max(MAX_DESTINATION_IDS_PER_DELETE_REQUEST, largest_server_group):
                raise ValidationError({"hog_function_ids": "Too many destination IDs."})
            soft_delete_alert_destinations(
                team_id=self.team_id,
                alert_id=str(alert.id),
                allowed_event_ids=METRICS_ALERT_EVENT_IDS,
                hog_function_ids=hog_function_ids,
            )

        report_user_action(
            request.user,
            "metrics alert destination deleted",
            {"alert_id": str(alert.id), "count": len(hog_function_ids)},
            request=request,
        )
        return Response(status=204)

    @extend_schema(responses={200: MetricsAlertEventSerializer(many=True)})
    @action(detail=True, methods=["GET"], url_path="events", required_scopes=["metrics:read"])
    def events(self, request: Request, *args: object, **kwargs: object) -> Response:
        alert = self.get_object()
        queryset = MetricsAlertEvent.objects.filter(alert=alert).order_by("-created_at")[:100]
        return Response(MetricsAlertEventSerializer(queryset, many=True).data)
