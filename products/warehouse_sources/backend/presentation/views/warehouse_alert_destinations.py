"""Notification destinations of a warehouse alert on the alerts platform.

The alert itself is created, edited and deleted through the platform API (`platform_alerts`). Its
destinations are HogFunctions this product owns, matched on the alert's configuration id, so they
are managed here.
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
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission

from products.alerts.backend.facade.destinations import (
    MAX_DESTINATIONS_PER_ALERT,
    build_alert_destination_config,
    create_alert_destination_hog_functions,
    destination_handles_event_kind,
    list_alert_destination_groups,
    redact_destination_data,
    soft_delete_alert_destinations,
    validate_destination_data,
)
from products.alerts_platform.backend.facade.api import get_configuration
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertDestinationValidationError,
    DestinationType,
    PagerDutyRegion,
    PagerDutySeverity,
    PlatformAlertConfigurationView,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.warehouse_sources.backend.facade.sync_alerts import (
    EVENT_IDS,
    EVENT_KIND_CONFIG,
    WAREHOUSE_ALERT_DESTINATION_TYPES,
)

MAX_DESTINATION_IDS_PER_DELETE_REQUEST = 100
WAREHOUSE_ALERT_KINDS = (SourceKind.WAREHOUSE_SOURCE.value, SourceKind.WAREHOUSE_DESTINATION.value)
# The warehouse data an alert names is gated by the same resource as the sources page.
WAREHOUSE_RESOURCE: Literal["external_data_source"] = "external_data_source"
_SLACK_CONTEXT_ELEMENTS = ("Project: <{project.url}|{project.name}>",)
# Choices classes for the serializers below. Each label is its value, so the OpenAPI enums keep the
# names their ENUM_NAME_OVERRIDES entries in posthog/settings/web.py give them. TextChoices supports
# this functional API at runtime, but its type stubs only describe member construction.
WarehouseAlertDestinationTypeChoices = cast(Any, models.TextChoices)(
    "WarehouseAlertDestinationTypeChoices",
    [(member.name, (member.value, member.value)) for member in WAREHOUSE_ALERT_DESTINATION_TYPES],
)
PagerDutySeverityChoices = cast(Any, models.TextChoices)(
    "PagerDutySeverityChoices", [(member.name, (member.value, member.value)) for member in PagerDutySeverity]
)
PagerDutyRegionChoices = cast(Any, models.TextChoices)(
    "PagerDutyRegionChoices", [(member.name, (member.value, member.value)) for member in PagerDutyRegion]
)


class WarehouseAlertDestinationSerializer(serializers.Serializer):
    hog_function_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="HogFunction IDs that make up this destination, one per alert event kind it handles. "
        "Send them all to the delete endpoint to remove the destination.",
    )
    type = serializers.ChoiceField(
        choices=WarehouseAlertDestinationTypeChoices.choices, help_text="Notification destination type."
    )
    enabled = serializers.BooleanField(
        help_text="Whether every HogFunction of the destination is enabled, so it notifies for every event kind."
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
        data = cast(AlertDestinationData, attrs)
        data["type"] = DestinationType(attrs["type"])
        try:
            validate_destination_data(data, allowed_destination_types=WAREHOUSE_ALERT_DESTINATION_TYPES)
        except AlertDestinationValidationError as error:
            raise as_drf_validation_error(error)
        return attrs


class WarehouseAlertDestinationCreatedSerializer(serializers.Serializer):
    hog_function_ids = serializers.ListField(
        child=serializers.UUIDField(), help_text="HogFunction IDs created for the destination, one per event kind."
    )


class WarehouseAlertDeleteDestinationSerializer(serializers.Serializer):
    hog_function_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=MAX_DESTINATION_IDS_PER_DELETE_REQUEST,
        help_text="HogFunction IDs of one destination, as the list endpoint returns them. They are deleted together.",
    )


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
        groups = list_alert_destination_groups(
            team_id=self.team_id,
            alert_id=str(alert.destination_alert_id),
            allowed_event_ids=EVENT_IDS[SourceKind(alert.source_kind)],
        )
        return Response(
            WarehouseAlertDestinationSerializer(
                [
                    {
                        "hog_function_ids": list(group.hog_function_ids),
                        "enabled": group.fully_enabled,
                        **redact_destination_data(group.data),
                    }
                    for group in groups
                ],
                many=True,
            ).data
        )

    @extend_schema(
        request=WarehouseAlertCreateDestinationSerializer,
        responses={
            201: WarehouseAlertDestinationCreatedSerializer,
            400: OpenApiResponse(description="The destination settings are invalid."),
        },
        description=(
            "Add a notification destination to a warehouse alert. One HogFunction is created per alert event kind "
            "(firing, resolved). A PagerDuty destination gets the incident opened and incident closed kinds "
            "instead, so each incident it opens is resolved."
        ),
    )
    @destinations.mapping.post
    def create_destination(self, request: Request, pk: str, **kwargs: Any) -> Response:
        alert = self._alert(pk)
        serializer = WarehouseAlertCreateDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = cast(AlertDestinationData, serializer.validated_data)
        source_kind = SourceKind(alert.source_kind)
        kinds = EVENT_KIND_CONFIG[source_kind]
        event_kinds = [kind for kind, spec in kinds.items() if destination_handles_event_kind(data["type"], spec)]
        configs = [
            build_alert_destination_config(
                spec=kinds[kind],
                alert_id=str(alert.destination_alert_id),
                alert_name=alert.name,
                data=data,
                slack_context_elements=_SLACK_CONTEXT_ELEMENTS,
            )
            for kind in event_kinds
        ]
        try:
            with transaction.atomic():
                # The alert's row stays locked until the destinations commit. A delete that got there
                # first leaves no row, and one that comes later waits, then removes these destinations too.
                if (
                    get_configuration(
                        team_id=self.team_id, source_kinds=WAREHOUSE_ALERT_KINDS, configuration_id=alert.id, lock=True
                    )
                    is None
                ):
                    raise NotFound()
                # Each destination is another message every time the alert fires, so one alert has only a few.
                existing = list_alert_destination_groups(
                    team_id=self.team_id,
                    alert_id=str(alert.destination_alert_id),
                    allowed_event_ids=EVENT_IDS[source_kind],
                )
                if len(existing) >= MAX_DESTINATIONS_PER_ALERT:
                    raise ValidationError(
                        f"This alert already has {MAX_DESTINATIONS_PER_ALERT} destinations. Remove one to add another."
                    )
                hog_function_ids = create_alert_destination_hog_functions(
                    configs,
                    team_id=self.team_id,
                    created_by_id=cast(User, request.user).id,
                    alert_id=str(alert.destination_alert_id),
                    allowed_event_ids=EVENT_IDS[source_kind],
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
                "event_kinds": event_kinds,
            },
            team=self.team,
            request=request,
        )
        return Response(
            WarehouseAlertDestinationCreatedSerializer({"hog_function_ids": list(hog_function_ids)}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=WarehouseAlertDeleteDestinationSerializer,
        responses={
            204: OpenApiResponse(description="The destination's HogFunctions are deleted."),
            400: OpenApiResponse(description="An ID does not belong to this alert, or names part of a destination."),
        },
        description="Delete one notification destination of a warehouse alert, all its HogFunctions together.",
    )
    @action(detail=True, methods=["POST"], url_path="destinations/delete")
    def delete_destination(self, request: Request, pk: str, **kwargs: Any) -> Response:
        alert = self._alert(pk)
        serializer = WarehouseAlertDeleteDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hog_function_ids: list[UUID] = serializer.validated_data["hog_function_ids"]
        try:
            soft_delete_alert_destinations(
                team_id=self.team_id,
                alert_id=str(alert.destination_alert_id),
                allowed_event_ids=EVENT_IDS[SourceKind(alert.source_kind)],
                hog_function_ids=hog_function_ids,
            )
        except AlertDestinationValidationError as error:
            raise as_drf_validation_error(error)

        report_user_action(
            cast(User, request.user),
            "warehouse alert destination deleted",
            {"alert_id": str(alert.id), "source_kind": alert.source_kind, "count": len(hog_function_ids)},
            team=self.team,
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
