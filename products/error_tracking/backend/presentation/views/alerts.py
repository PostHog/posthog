from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.facade import alerts as alerts_facade
from products.error_tracking.backend.models import ErrorTrackingAlert, ErrorTrackingAlertDestination

# PostgreSQL integer column bound; larger values would 500 on save.
MAX_THROTTLE_SECONDS = 2**31 - 1


class ErrorTrackingAlertDestinationRequestSerializer(serializers.Serializer):
    # Request-side twin of ErrorTrackingAlertDestinationSerializer without the
    # server-generated id, so generated clients don't require one on create.
    channel_type = serializers.ChoiceField(
        choices=ErrorTrackingAlertDestination.ChannelType.choices,
        help_text="Delivery channel for notifications.",
    )
    integration_id = serializers.IntegerField(
        allow_null=True,
        required=False,
        default=None,
        help_text="ID of the workspace integration used to deliver notifications (required for Slack).",
    )
    config = serializers.JSONField(help_text='Channel-specific delivery settings, e.g. {"channel": "C0123"} for Slack.')


class ErrorTrackingAlertDestinationSerializer(ErrorTrackingAlertDestinationRequestSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier of the destination.")


class ErrorTrackingAlertSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier of the alert.")
    name = serializers.CharField(help_text="Human-readable name of the alert.")
    enabled = serializers.BooleanField(help_text="Whether the alert currently fires notifications.")
    triggers = serializers.ListField(
        child=serializers.ChoiceField(choices=ErrorTrackingAlert.Trigger.choices),
        help_text="Issue lifecycle events that open a notification thread for an issue.",
    )
    filters = serializers.JSONField(
        help_text="Property filters a transition must match to open a notification thread. "
        "Same shape as hog function filters, including the compiled bytecode."
    )
    throttle_seconds = serializers.IntegerField(
        help_text="Minimum seconds between thread-opening notifications per issue. 0 disables the throttle."
    )
    destinations = ErrorTrackingAlertDestinationSerializer(
        many=True, help_text="Delivery targets notifications fan out to."
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the alert was created.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the alert was last updated.")


class ErrorTrackingAlertCreateRequestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=400, help_text="Human-readable name of the alert.")
    triggers = serializers.ListField(
        child=serializers.ChoiceField(choices=ErrorTrackingAlert.Trigger.choices),
        allow_empty=False,
        help_text="Issue lifecycle events that open a notification thread for an issue.",
    )
    filters = serializers.JSONField(
        required=False,
        default=dict,
        help_text="Property filters a transition must match to open a notification thread. "
        "Same shape as hog function filters; the bytecode is compiled on save.",
    )
    throttle_seconds = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        max_value=MAX_THROTTLE_SECONDS,
        help_text="Minimum seconds between thread-opening notifications per issue. 0 disables the throttle.",
    )
    destinations = ErrorTrackingAlertDestinationRequestSerializer(
        many=True,
        allow_empty=False,
        help_text="Delivery targets notifications fan out to.",
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
    filters = serializers.JSONField(
        required=False,
        help_text="Property filters a transition must match to open a notification thread. "
        "Omit to keep the current filters.",
    )
    throttle_seconds = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=MAX_THROTTLE_SECONDS,
        help_text="Minimum seconds between thread-opening notifications per issue. Omit to keep the current value.",
    )
    destinations = ErrorTrackingAlertDestinationRequestSerializer(
        many=True,
        required=False,
        allow_empty=False,
        help_text="Delivery targets notifications fan out to. When provided, replaces all current destinations.",
    )


class ErrorTrackingAlertViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    serializer_class = ErrorTrackingAlertSerializer

    def initial(self, request: Request, *args, **kwargs) -> None:
        super().initial(request, *args, **kwargs)
        if not alerts_facade.native_alerts_enabled(self.team.id):
            raise PermissionDenied("This feature is not available.")

    def list(self, request: Request, *args, **kwargs) -> Response:
        alerts = alerts_facade.list_alerts(self.team.id)
        page = self.paginate_queryset(alerts)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(alerts, many=True).data)

    def retrieve(self, request: Request, *args, pk=None, **kwargs) -> Response:
        alert = alerts_facade.get_alert(self.team.id, pk)
        if alert is None:
            raise NotFound()
        return Response(self.get_serializer(alert).data)

    @validated_request(
        request_serializer=ErrorTrackingAlertCreateRequestSerializer,
        responses={201: OpenApiResponse(response=ErrorTrackingAlertSerializer)},
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        try:
            alert = alerts_facade.create_alert(
                self.team.id,
                name=request.validated_data["name"],
                triggers=request.validated_data["triggers"],
                filters=request.validated_data["filters"],
                throttle_seconds=request.validated_data["throttle_seconds"],
                destinations=request.validated_data["destinations"],
                created_by=request.user,
            )
        except alerts_facade.AlertValidationError as err:
            raise ValidationError(str(err)) from err
        return Response(self.get_serializer(alert).data, status=status.HTTP_201_CREATED)

    def _apply_alert_update(self, request: ValidatedRequest, pk: str) -> Response:
        try:
            alert = alerts_facade.update_alert(
                self.team.id,
                pk,
                name=request.validated_data.get("name"),
                enabled=request.validated_data.get("enabled"),
                triggers=request.validated_data.get("triggers"),
                filters=request.validated_data.get("filters"),
                throttle_seconds=request.validated_data.get("throttle_seconds"),
                destinations=request.validated_data.get("destinations"),
            )
        except alerts_facade.AlertValidationError as err:
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

    def destroy(self, request: Request, *args, pk=None, **kwargs) -> Response:
        if not alerts_facade.delete_alert(self.team.id, pk):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)
