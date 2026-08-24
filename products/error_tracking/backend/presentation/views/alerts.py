from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.facade import api as error_tracking_api
from products.error_tracking.backend.models import ErrorTrackingAlert


class ErrorTrackingAlertSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier of the alert.")
    name = serializers.CharField(help_text="Human-readable name of the alert.")
    enabled = serializers.BooleanField(help_text="Whether the alert currently fires notifications.")
    triggers = serializers.ListField(
        child=serializers.ChoiceField(choices=ErrorTrackingAlert.Trigger.choices),
        help_text="Issue lifecycle events that open a notification thread for an issue.",
    )
    channel_type = serializers.ChoiceField(
        choices=ErrorTrackingAlert.ChannelType.choices,
        help_text="Delivery channel for notifications.",
    )
    integration_id = serializers.IntegerField(
        allow_null=True,
        help_text="ID of the workspace integration used to deliver notifications (required for Slack).",
    )
    config = serializers.JSONField(help_text='Channel-specific delivery settings, e.g. {"channel": "C0123"} for Slack.')
    created_at = serializers.DateTimeField(read_only=True, help_text="When the alert was created.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the alert was last updated.")


class ErrorTrackingAlertConfigSerializer(serializers.Serializer):
    channel = serializers.CharField(
        help_text="Slack channel ID to post notifications to.",
    )


class ErrorTrackingAlertCreateRequestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=400, help_text="Human-readable name of the alert.")
    triggers = serializers.ListField(
        child=serializers.ChoiceField(choices=ErrorTrackingAlert.Trigger.choices),
        allow_empty=False,
        help_text="Issue lifecycle events that open a notification thread for an issue.",
    )
    channel_type = serializers.ChoiceField(
        choices=ErrorTrackingAlert.ChannelType.choices,
        help_text="Delivery channel for notifications.",
    )
    integration_id = serializers.IntegerField(
        help_text="ID of the workspace integration used to deliver notifications.",
    )
    config = ErrorTrackingAlertConfigSerializer(
        help_text='Channel-specific delivery settings, e.g. {"channel": "C0123"} for Slack.',
    )


class ErrorTrackingAlertUpdateRequestSerializer(serializers.Serializer):
    name = serializers.CharField(
        required=False, max_length=400, help_text="Human-readable name of the alert. Omit to keep the current name."
    )
    enabled = serializers.BooleanField(
        required=False, help_text="Whether the alert fires notifications. Omit to keep the current state."
    )
    triggers = serializers.ListField(
        child=serializers.ChoiceField(choices=ErrorTrackingAlert.Trigger.choices),
        required=False,
        allow_empty=False,
        help_text="Issue lifecycle events that open a notification thread. Omit to keep the current triggers.",
    )
    config = ErrorTrackingAlertConfigSerializer(
        required=False,
        help_text="Channel-specific delivery settings. Omit to keep the current config.",
    )


class ErrorTrackingAlertViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    serializer_class = ErrorTrackingAlertSerializer

    def list(self, request, *args, **kwargs) -> Response:
        alerts = error_tracking_api.list_alerts(self.team.id)
        page = self.paginate_queryset(alerts)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(alerts, many=True).data)

    def retrieve(self, request, *args, pk=None, **kwargs) -> Response:
        alert = error_tracking_api.get_alert(self.team.id, pk)
        if alert is None:
            raise NotFound()
        return Response(self.get_serializer(alert).data)

    @validated_request(
        request_serializer=ErrorTrackingAlertCreateRequestSerializer,
        responses={201: OpenApiResponse(response=ErrorTrackingAlertSerializer)},
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        try:
            alert = error_tracking_api.create_alert(
                self.team.id,
                name=request.validated_data["name"],
                triggers=request.validated_data["triggers"],
                channel_type=request.validated_data["channel_type"],
                integration_id=request.validated_data["integration_id"],
                config=request.validated_data["config"],
                created_by=request.user,
            )
        except error_tracking_api.AlertValidationError as err:
            raise ValidationError(str(err)) from err
        return Response(self.get_serializer(alert).data, status=status.HTTP_201_CREATED)

    def _apply_alert_update(self, request: ValidatedRequest, pk: str) -> Response:
        try:
            alert = error_tracking_api.update_alert(
                self.team.id,
                pk,
                name=request.validated_data.get("name"),
                enabled=request.validated_data.get("enabled"),
                triggers=request.validated_data.get("triggers"),
                config=request.validated_data.get("config"),
            )
        except error_tracking_api.AlertValidationError as err:
            raise ValidationError(str(err)) from err
        if alert is None:
            raise NotFound()
        return Response(self.get_serializer(alert).data)

    @validated_request(
        request_serializer=ErrorTrackingAlertUpdateRequestSerializer,
        responses={200: OpenApiResponse(response=ErrorTrackingAlertSerializer)},
    )
    def update(self, request: ValidatedRequest, *args, pk=None, **kwargs) -> Response:
        return self._apply_alert_update(request, pk)

    @validated_request(
        request_serializer=ErrorTrackingAlertUpdateRequestSerializer,
        responses={200: OpenApiResponse(response=ErrorTrackingAlertSerializer)},
    )
    def partial_update(self, request: ValidatedRequest, *args, pk=None, **kwargs) -> Response:
        return self._apply_alert_update(request, pk)

    def destroy(self, request, *args, pk=None, **kwargs) -> Response:
        if not error_tracking_api.delete_alert(self.team.id, pk):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)
