"""Notification destinations of a metrics alert on the alerts platform.

The alert itself is created, edited and deleted through the platform API (`platform_alerts`). Its
destinations are `AlertDestination` rows the platform delivers to, managed here with the metrics
access rules.
"""

from typing import Any, Literal, cast
from uuid import UUID

from django.db import models, transaction

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.exceptions import Conflict, as_drf_validation_error
from posthog.integrations import IntegrationManager
from posthog.models import User
from posthog.models.integration import SLACK_INTEGRATION_KINDS
from posthog.permissions import PostHogFeatureFlagPermission

from products.alerts.backend.facade.destinations import (
    MAX_DESTINATION_IDS_PER_DELETE_REQUEST,
    MAX_DESTINATIONS_PER_ALERT,
    redact_destination_data,
    validate_destination_data,
)
from products.alerts_platform.backend.facade.api import (
    create_alert_destinations,
    delete_alert_destinations,
    get_configuration,
    list_alert_destinations,
)
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertDestinationValidationError,
    AlertEventKind,
    DestinationType,
    NewAlertDestination,
    PagerDutyRegion,
    PagerDutySeverity,
    PlatformAlertConfigurationView,
    SourceKind,
    StoredAlertDestination,
)
from products.alerts_platform.backend.facade.delivery import refused_destination
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.metrics.backend.facade.alerts import METRICS_ALERT_DESTINATION_TYPES

METRICS_ALERT_KINDS = (SourceKind.METRICS.value,)
# The metrics an alert queries are gated by the same resource as the metrics scene.
METRICS_RESOURCE: Literal["metrics"] = "metrics"
# What a destination hears when the request names no kinds. An incident manager hears the trigger and
# resolve of every firing, which delivery sends it for firing and resolved.
_DEFAULT_EVENT_KINDS: dict[DestinationType, tuple[AlertEventKind, ...]] = {
    DestinationType.PAGERDUTY: (AlertEventKind.FIRING, AlertEventKind.RESOLVED),
}
_MESSAGE_EVENT_KINDS = (AlertEventKind.FIRING, AlertEventKind.RESOLVED, AlertEventKind.ERRORED, AlertEventKind.BROKEN)
_WEBHOOK_FIELDS = ("webhook_url",)
# The fields each type stores. Redaction knows only its own type's credential, so a field of another
# type would be stored and then shown in full.
_FIELDS_BY_TYPE: dict[DestinationType, tuple[str, ...]] = {
    DestinationType.SLACK: ("slack_workspace_id", "slack_channel_id", "slack_channel_name"),
    DestinationType.WEBHOOK: _WEBHOOK_FIELDS,
    DestinationType.TEAMS: _WEBHOOK_FIELDS,
    DestinationType.DISCORD: _WEBHOOK_FIELDS,
    DestinationType.PAGERDUTY: ("pagerduty_routing_key", "pagerduty_severity", "pagerduty_region"),
}
# Choices classes for the serializers below. TextChoices supports this functional API at runtime, but
# its type stubs only describe member construction. The destination types carry their display labels,
# so the OpenAPI enum is named after this class (MetricsAlertDestinationTypeEnum). The others keep
# label equal to value, so they share the names their ENUM_NAME_OVERRIDES entries give them.
MetricsAlertDestinationType = cast(Any, models.TextChoices)(
    "MetricsAlertDestinationType",
    [(member.name, (member.value, member.label)) for member in METRICS_ALERT_DESTINATION_TYPES],
)
PagerDutySeverityChoices = cast(Any, models.TextChoices)(
    "PagerDutySeverityChoices", [(member.name, (member.value, member.value)) for member in PagerDutySeverity]
)
PagerDutyRegionChoices = cast(Any, models.TextChoices)(
    "PagerDutyRegionChoices", [(member.name, (member.value, member.value)) for member in PagerDutyRegion]
)
MetricsAlertDestinationEventKind = cast(Any, models.TextChoices)(
    "MetricsAlertDestinationEventKind",
    [(member.name, (member.value, member.value)) for member in _MESSAGE_EVENT_KINDS],
)


class MetricsAlertDestinationSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the destination. Send it to the delete endpoint to remove it.")
    type = serializers.ChoiceField(
        choices=MetricsAlertDestinationType.choices, help_text="Notification destination type."
    )
    enabled = serializers.BooleanField(help_text="Whether the destination is sent to.")
    event_kinds = serializers.ListField(
        child=serializers.ChoiceField(choices=MetricsAlertDestinationEventKind.choices),
        help_text="The alert transitions the destination hears about. A PagerDuty destination hears the incident "
        "trigger and resolve of every firing.",
    )
    slack_workspace_id = serializers.IntegerField(
        required=False, help_text="Integration ID of the Slack workspace. Set when type=slack."
    )
    slack_channel_id = serializers.CharField(required=False, help_text="Slack channel ID. Set when type=slack.")
    slack_channel_name = serializers.CharField(
        required=False, help_text="Human-readable Slack channel name. Set when type=slack."
    )
    webhook_url = serializers.CharField(
        required=False,
        help_text="Webhook endpoint reduced to scheme and host. The path, query and userinfo carry the secret.",
    )
    pagerduty_routing_key = serializers.CharField(
        required=False, help_text="PagerDuty integration key reduced to its last four characters."
    )
    pagerduty_severity = serializers.ChoiceField(
        choices=PagerDutySeverityChoices.choices,
        required=False,
        help_text="Severity of the PagerDuty incident.",
    )
    pagerduty_region = serializers.ChoiceField(
        choices=PagerDutyRegionChoices.choices,
        required=False,
        help_text="PagerDuty service region the events go to.",
    )


class MetricsAlertCreateDestinationSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=MetricsAlertDestinationType.choices, help_text="Notification destination type."
    )
    slack_workspace_id = serializers.IntegerField(
        required=False, help_text="Integration ID for the Slack workspace. Required when type=slack."
    )
    slack_channel_id = serializers.CharField(required=False, help_text="Slack channel ID. Required when type=slack.")
    slack_channel_name = serializers.CharField(
        required=False, allow_blank=True, help_text="Human-readable channel name for display."
    )
    webhook_url = serializers.URLField(
        required=False, help_text="HTTPS endpoint to post to. Required for webhook, teams and discord."
    )
    pagerduty_routing_key = serializers.CharField(
        required=False,
        trim_whitespace=True,
        help_text="Integration key of a PagerDuty Events API v2 integration. Required when type=pagerduty.",
    )
    pagerduty_severity = serializers.ChoiceField(
        choices=PagerDutySeverityChoices.choices,
        required=False,
        default=PagerDutySeverity.CRITICAL.value,
        help_text="Severity PagerDuty records on the incident. Used when type=pagerduty.",
    )
    pagerduty_region = serializers.ChoiceField(
        choices=PagerDutyRegionChoices.choices,
        required=False,
        default=PagerDutyRegion.US.value,
        help_text="PagerDuty service region of the account. Used when type=pagerduty.",
    )
    event_kinds = serializers.ListField(
        child=serializers.ChoiceField(choices=MetricsAlertDestinationEventKind.choices),
        required=False,
        min_length=1,
        help_text="The alert transitions to send about. Defaults to every kind, or to firing and resolved for "
        "PagerDuty, which then hears each incident's trigger and resolve.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        destination_type = DestinationType(attrs["type"])
        # The PagerDuty fields have defaults, so they arrive for every type. Each type keeps only its own.
        data = cast(
            AlertDestinationData,
            {key: attrs[key] for key in _FIELDS_BY_TYPE[destination_type] if key in attrs},
        )
        data["type"] = destination_type
        try:
            validate_destination_data(data, allowed_destination_types=METRICS_ALERT_DESTINATION_TYPES)
        except AlertDestinationValidationError as error:
            raise as_drf_validation_error(error)
        # A destination native delivery would refuse is saved and then never notifies, so refuse it here.
        if refusal := refused_destination(data):
            raise ValidationError({"webhook_url": refusal} if data.get("webhook_url") is not None else refusal)
        kinds = attrs.get("event_kinds") or _DEFAULT_EVENT_KINDS.get(data["type"], _MESSAGE_EVENT_KINDS)
        return {"data": data, "event_kinds": tuple(AlertEventKind(kind) for kind in kinds)}


class MetricsAlertDeleteDestinationSerializer(serializers.Serializer):
    destination_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=MAX_DESTINATION_IDS_PER_DELETE_REQUEST,
        help_text="IDs of the destinations to delete, as the list endpoint returns them.",
    )


def _serialized(destination: StoredAlertDestination) -> dict[str, Any]:
    return {
        "id": destination.id,
        "enabled": destination.enabled,
        "event_kinds": [kind.value for kind in destination.event_kinds],
        **redact_destination_data(destination.data),
    }


class MetricsAlertDestinationViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Destinations of a metrics alert. The URL's ID is the alert's platform configuration ID."""

    scope_object = "alert"
    posthog_feature_flag = "platform-alerts"
    permission_classes = [PostHogFeatureFlagPermission]

    def dangerously_get_required_scopes(self, request: Request, view: APIView) -> list[str]:
        # A destination exposes the metrics alert it belongs to, so a key needs the metrics scope too.
        access = "read" if request.method in SAFE_METHODS else "write"
        return [f"alert:{access}", f"{METRICS_RESOURCE}:{access}"]

    def _alert(self, pk: str) -> PlatformAlertConfigurationView:
        level: Literal["viewer", "editor"] = "viewer" if self.request.method in SAFE_METHODS else "editor"
        if not self.user_access_control.check_access_level_for_resource(METRICS_RESOURCE, level):
            raise PermissionDenied("You don't have access to metrics in this project.")
        alert = get_configuration(
            team_id=self.team_id,
            source_kinds=METRICS_ALERT_KINDS,
            configuration_id=serializers.UUIDField().run_validation(pk),
        )
        if alert is None:
            raise NotFound()
        if alert.owner != PlatformAlertOwner.PLATFORM:
            raise Conflict("This alert has no destinations to manage here.")
        return alert

    @extend_schema(
        responses={200: MetricsAlertDestinationSerializer(many=True)},
        description="List the notification destinations of a metrics alert.",
    )
    @action(detail=True, methods=["GET"], url_path="destinations", pagination_class=None)
    def destinations(self, request: Request, pk: str, **kwargs: Any) -> Response:
        alert = self._alert(pk)
        destinations = list_alert_destinations(team_id=self.team_id, configuration_id=alert.id)
        return Response(MetricsAlertDestinationSerializer([_serialized(d) for d in destinations], many=True).data)

    @extend_schema(
        request=MetricsAlertCreateDestinationSerializer,
        responses={
            201: MetricsAlertDestinationSerializer,
            400: OpenApiResponse(description="The destination settings are invalid."),
        },
        description=(
            "Add a notification destination to a metrics alert. It hears the transitions in `event_kinds`. "
            "A PagerDuty destination opens an incident when the alert fires and resolves it when the alert resolves."
        ),
    )
    @destinations.mapping.post
    def create_destination(self, request: Request, pk: str, **kwargs: Any) -> Response:
        alert = self._alert(pk)
        serializer = MetricsAlertCreateDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = cast(AlertDestinationData, serializer.validated_data["data"])
        event_kinds: tuple[AlertEventKind, ...] = serializer.validated_data["event_kinds"]
        # Native delivery looks the workspace up by team and kind, so a destination naming any other
        # integration would be saved and never notify.
        if data["type"] == DestinationType.SLACK and data["slack_workspace_id"] not in IntegrationManager.kinds(
            *SLACK_INTEGRATION_KINDS, auth_types="any"
        ).get_many(self.team_id, [data["slack_workspace_id"]]):
            raise ValidationError({"slack_workspace_id": "Choose a Slack workspace connected to this project."})
        try:
            with transaction.atomic():
                # The alert's row stays locked until the destinations commit. A delete that got there
                # first leaves no row, and one that comes later waits, then removes these destinations too.
                if (
                    get_configuration(
                        team_id=self.team_id,
                        source_kinds=METRICS_ALERT_KINDS,
                        configuration_id=alert.id,
                        lock=True,
                    )
                    is None
                ):
                    raise NotFound()
                # Each destination is another message every time the alert fires, so one alert has only a few.
                existing = list_alert_destinations(team_id=self.team_id, configuration_id=alert.id)
                if len(existing) >= MAX_DESTINATIONS_PER_ALERT:
                    raise ValidationError(
                        f"This alert already has {MAX_DESTINATIONS_PER_ALERT} destinations. Remove one to add another."
                    )
                (created,) = create_alert_destinations(
                    team_id=self.team_id,
                    configuration_id=alert.id,
                    destinations=(NewAlertDestination(data=data, event_kinds=event_kinds),),
                )
        except AlertDestinationValidationError as error:
            raise as_drf_validation_error(error)

        # Robust, so an analytics failure, such as a malformed Referer, cannot fail a create that committed.
        transaction.on_commit(
            lambda: self._track(
                "created",
                {"alert_id": str(alert.id), "type": data["type"], "event_kinds": [kind.value for kind in event_kinds]},
            ),
            robust=True,
        )
        return Response(MetricsAlertDestinationSerializer(_serialized(created)).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=MetricsAlertDeleteDestinationSerializer,
        responses={
            204: OpenApiResponse(description="The destinations are deleted. An ID of another alert is ignored."),
        },
        description="Delete notification destinations of a metrics alert.",
    )
    @action(detail=True, methods=["POST"], url_path="destinations/delete")
    def delete_destination(self, request: Request, pk: str, **kwargs: Any) -> Response:
        alert = self._alert(pk)
        serializer = MetricsAlertDeleteDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        destination_ids: list[UUID] = serializer.validated_data["destination_ids"]
        deleted = delete_alert_destinations(
            team_id=self.team_id, configuration_id=alert.id, destination_ids=destination_ids
        )

        transaction.on_commit(
            lambda: self._track("deleted", {"alert_id": str(alert.id), "count": deleted}), robust=True
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _track(self, action: Literal["created", "deleted"], properties: dict[str, Any]) -> None:
        report_user_action(
            cast(User, self.request.user),
            f"metrics alert destination {action}",
            properties,
            team=self.team,
            request=self.request,
        )
