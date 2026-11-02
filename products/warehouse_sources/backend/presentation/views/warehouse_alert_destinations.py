"""Notification destinations of a warehouse alert on the alerts platform.

The alert itself is created, edited and deleted through the platform API (`platform_alerts`). Its
destinations are `AlertDestination` rows the platform keeps, managed here so the warehouse access
checks apply to them.
"""

from typing import Any, Final, Literal, cast
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
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission

from products.alerts.backend.facade.destinations import (
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
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.warehouse_sources.backend.facade.sync_alerts import (
    WAREHOUSE_ALERT_DESTINATION_TYPES,
    WAREHOUSE_DESTINATION_EVENT_KINDS,
)

WAREHOUSE_ALERT_KINDS = (SourceKind.WAREHOUSE_SOURCE.value, SourceKind.WAREHOUSE_DESTINATION.value)
# The warehouse data an alert names is gated by the same resource as the sources page.
WAREHOUSE_RESOURCE: Literal["external_data_source"] = "external_data_source"
# Choices classes for the serializers below. Each label is its value, so the OpenAPI enums keep the
# names their ENUM_NAME_OVERRIDES entries in posthog/settings/web.py give them. TextChoices supports
# this functional API at runtime, but its type stubs only describe member construction.
WarehouseAlertDestinationTypeChoices = cast(Any, models.TextChoices)(
    "WarehouseAlertDestinationTypeChoices",
    [(member.name, (member.value, member.value)) for member in WAREHOUSE_ALERT_DESTINATION_TYPES],
)
WarehouseAlertEventKindChoices = cast(Any, models.TextChoices)(
    "WarehouseAlertEventKindChoices",
    [(member.name, (member.value, member.value)) for member in WAREHOUSE_DESTINATION_EVENT_KINDS],
)
PagerDutySeverityChoices = cast(Any, models.TextChoices)(
    "PagerDutySeverityChoices", [(member.name, (member.value, member.value)) for member in PagerDutySeverity]
)
PagerDutyRegionChoices = cast(Any, models.TextChoices)(
    "PagerDutyRegionChoices", [(member.name, (member.value, member.value)) for member in PagerDutyRegion]
)
_EVENT_KINDS_HELP = (
    "Which transitions send a message. A PagerDuty destination opens an incident when the alert fires and "
    "resolves it when the alert resolves, whatever this lists."
)


_WEBHOOK_FIELDS: Final = ("webhook_url",)
# The settings each type keeps. The serializer accepts every type's fields and fills the PagerDuty
# defaults for all of them, and a field of another type can hold a credential that its redaction misses.
_FIELDS_BY_TYPE: Final[dict[DestinationType, tuple[str, ...]]] = {
    DestinationType.SLACK: ("slack_workspace_id", "slack_channel_id", "slack_channel_name"),
    DestinationType.WEBHOOK: _WEBHOOK_FIELDS,
    DestinationType.TEAMS: _WEBHOOK_FIELDS,
    DestinationType.DISCORD: _WEBHOOK_FIELDS,
    DestinationType.PAGERDUTY: ("pagerduty_routing_key", "pagerduty_severity", "pagerduty_region"),
}


def _split(attrs: dict[str, Any]) -> tuple[AlertDestinationData, tuple[AlertEventKind, ...]]:
    """A create request's destination settings, apart from the kinds it asks to hear about."""
    destination_type = DestinationType(attrs["type"])
    data: dict[str, Any] = {key: attrs[key] for key in _FIELDS_BY_TYPE[destination_type] if key in attrs}
    data["type"] = destination_type
    return cast(AlertDestinationData, data), tuple(AlertEventKind(kind) for kind in attrs["event_kinds"])


class WarehouseAlertDestinationSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Destination ID. Send it to the delete endpoint to remove the destination.")
    type = serializers.ChoiceField(
        choices=WarehouseAlertDestinationTypeChoices.choices, help_text="Notification destination type."
    )
    enabled = serializers.BooleanField(help_text="Whether the destination is sent to.")
    event_kinds = serializers.ListField(
        child=serializers.ChoiceField(choices=WarehouseAlertEventKindChoices.choices), help_text=_EVENT_KINDS_HELP
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


class WarehouseAlertCreateDestinationSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=WarehouseAlertDestinationTypeChoices.choices, help_text="Notification destination type."
    )
    event_kinds = serializers.ListField(
        child=serializers.ChoiceField(choices=WarehouseAlertEventKindChoices.choices),
        required=False,
        min_length=1,
        default=[kind.value for kind in WAREHOUSE_DESTINATION_EVENT_KINDS],
        help_text=f"{_EVENT_KINDS_HELP} Defaults to every kind.",
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

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        data, _ = _split(attrs)
        try:
            validate_destination_data(data, allowed_destination_types=WAREHOUSE_ALERT_DESTINATION_TYPES)
        except AlertDestinationValidationError as error:
            raise as_drf_validation_error(error)
        return attrs


class WarehouseAlertDeleteDestinationSerializer(serializers.Serializer):
    destination_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=MAX_DESTINATIONS_PER_ALERT,
        help_text="IDs of the alert's destinations to delete, as the list endpoint returns them.",
    )


def _serialized(destination: StoredAlertDestination) -> dict[str, Any]:
    return WarehouseAlertDestinationSerializer(
        {
            "id": destination.id,
            "enabled": destination.enabled,
            "event_kinds": [kind.value for kind in destination.event_kinds],
            **redact_destination_data(destination.data),
        }
    ).data


class WarehouseAlertDestinationViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Destinations of a warehouse alert. The URL's ID is the alert's platform configuration ID."""

    scope_object = "alert"
    posthog_feature_flag = "platform-alerts"
    permission_classes = [PostHogFeatureFlagPermission]

    def dangerously_get_required_scopes(self, request: Request, view: APIView) -> list[str]:
        # A destination exposes the warehouse alert it belongs to, so a key needs the warehouse scope too.
        access = "read" if request.method in SAFE_METHODS else "write"
        return [f"alert:{access}", f"{WAREHOUSE_RESOURCE}:{access}"]

    def _alert(self, pk: str) -> PlatformAlertConfigurationView:
        level: Literal["viewer", "editor"] = "viewer" if self.request.method in SAFE_METHODS else "editor"
        if not self.user_access_control.check_access_level_for_resource(WAREHOUSE_RESOURCE, level):
            raise PermissionDenied("You don't have access to warehouse sources in this project.")
        alert = get_configuration(
            team_id=self.team_id,
            source_kinds=WAREHOUSE_ALERT_KINDS,
            configuration_id=serializers.UUIDField().run_validation(pk),
        )
        if alert is None:
            raise NotFound()
        if alert.owner != PlatformAlertOwner.PLATFORM:
            raise Conflict("This alert has no destinations to manage here.")
        return alert

    @extend_schema(
        responses={200: WarehouseAlertDestinationSerializer(many=True)},
        description="List the notification destinations of a warehouse alert.",
    )
    @action(detail=True, methods=["GET"], url_path="destinations", pagination_class=None)
    def destinations(self, request: Request, pk: str, **kwargs: Any) -> Response:
        alert = self._alert(pk)
        return Response(
            [
                _serialized(destination)
                for destination in list_alert_destinations(team_id=self.team_id, configuration_id=alert.id)
            ]
        )

    @extend_schema(
        request=WarehouseAlertCreateDestinationSerializer,
        responses={
            201: WarehouseAlertDestinationSerializer,
            400: OpenApiResponse(description="The destination settings are invalid."),
        },
        description="Add a notification destination to a warehouse alert.",
    )
    @destinations.mapping.post
    def create_destination(self, request: Request, pk: str, **kwargs: Any) -> Response:
        alert = self._alert(pk)
        serializer = WarehouseAlertCreateDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data, event_kinds = _split(serializer.validated_data)
        try:
            with transaction.atomic():
                # The alert's row stays locked until the destination commits, so two adds cannot both
                # pass the limit. A delete that got there first leaves no row.
                if (
                    get_configuration(
                        team_id=self.team_id, source_kinds=WAREHOUSE_ALERT_KINDS, configuration_id=alert.id, lock=True
                    )
                    is None
                ):
                    raise NotFound()
                # Each destination is another message every time the alert fires, so one alert has only a few.
                if (
                    len(list_alert_destinations(team_id=self.team_id, configuration_id=alert.id))
                    >= MAX_DESTINATIONS_PER_ALERT
                ):
                    raise ValidationError(
                        f"This alert already has {MAX_DESTINATIONS_PER_ALERT} destinations. Remove one to add another."
                    )
                (created,) = create_alert_destinations(
                    team_id=self.team_id,
                    configuration_id=alert.id,
                    destinations=[NewAlertDestination(data=data, event_kinds=event_kinds)],
                )
        except AlertDestinationValidationError as error:
            raise as_drf_validation_error(error)

        report_user_action(
            cast(User, request.user),
            "warehouse alert destination created",
            {
                "alert_id": str(alert.id),
                "source_kind": alert.source_kind,
                "type": data["type"],
                "event_kinds": [kind.value for kind in event_kinds],
            },
            team=self.team,
            request=request,
        )
        return Response(_serialized(created), status=status.HTTP_201_CREATED)

    @extend_schema(
        request=WarehouseAlertDeleteDestinationSerializer,
        responses={
            204: OpenApiResponse(description="The destinations are deleted."),
            400: OpenApiResponse(description="An ID does not belong to this alert."),
        },
        description="Delete notification destinations of a warehouse alert.",
    )
    @action(detail=True, methods=["POST"], url_path="destinations/delete")
    def delete_destination(self, request: Request, pk: str, **kwargs: Any) -> Response:
        alert = self._alert(pk)
        serializer = WarehouseAlertDeleteDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        destination_ids: set[UUID] = set(serializer.validated_data["destination_ids"])
        # A partial delete would leave the caller unsure which destinations remain, so refuse first.
        known = {
            destination.id for destination in list_alert_destinations(team_id=self.team_id, configuration_id=alert.id)
        }
        if unknown := sorted(str(destination_id) for destination_id in destination_ids - known):
            raise ValidationError({"destination_ids": f"No destination of this alert has the ID {', '.join(unknown)}."})
        delete_alert_destinations(team_id=self.team_id, configuration_id=alert.id, destination_ids=destination_ids)

        report_user_action(
            cast(User, request.user),
            "warehouse alert destination deleted",
            {"alert_id": str(alert.id), "source_kind": alert.source_kind, "count": len(destination_ids)},
            team=self.team,
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
