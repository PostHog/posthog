from typing import Any, Never

from django.conf import settings

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import ErrorResponseSerializer, action
from posthog.permissions import PostHogFeatureFlagPermission, TeamMemberStrictManagementPermission

from products.secure_connections.backend.client import (
    SecureConnectionServiceError,
    SecureConnectionServiceNotConfigured,
)
from products.secure_connections.backend.facade import api
from products.secure_connections.backend.facade.contracts import SecureConnection
from products.secure_connections.backend.presentation.serializers import (
    SecureConnectionApprovalSerializer,
    SecureConnectionApprovalsSerializer,
    SecureConnectionEnrollmentSerializer,
    SecureConnectionStatusSerializer,
    SecureConnectionTestSerializer,
)


class SecureConnectionUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Secure connections are unavailable. Try again later."
    default_code = "secure_connection_unavailable"


class SecureConnectionFeatureFlagPermission(PostHogFeatureFlagPermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        return settings.DEBUG or super().has_permission(request, view)


class SecureConnectionSchema(AutoSchema):
    def _is_list_view(self, serializer: object = None) -> bool:
        return False


class SecureConnectionViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "INTERNAL"
    permission_classes = [SecureConnectionFeatureFlagPermission, TeamMemberStrictManagementPermission]
    posthog_feature_flag = "secure-connections"
    pagination_class = None
    schema = SecureConnectionSchema()

    def _handle_service_error(self, error: SecureConnectionServiceError) -> Never:
        if isinstance(error, SecureConnectionServiceNotConfigured):
            raise SecureConnectionUnavailable("Secure connections are not configured for this deployment.") from error
        raise SecureConnectionUnavailable() from error

    @extend_schema(
        responses={
            200: SecureConnectionStatusSerializer,
            503: OpenApiResponse(
                response=ErrorResponseSerializer, description="The connection service is unavailable."
            ),
        },
        description="Get the secure connection status for a project.",
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            connection_status = api.get_status(self.team_id)
        except SecureConnectionServiceError as error:
            self._handle_service_error(error)
        return Response(SecureConnectionStatusSerializer(connection_status).data)

    @extend_schema(
        request=None,
        responses={
            201: SecureConnectionEnrollmentSerializer,
            503: OpenApiResponse(
                response=ErrorResponseSerializer, description="The connection service is unavailable."
            ),
        },
        description="Create or replace the enrollment credential for a project's secure connection.",
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            enrollment = api.create_enrollment(self.team_id)
        except SecureConnectionServiceError as error:
            self._handle_service_error(error)
        return Response(SecureConnectionEnrollmentSerializer(enrollment).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=None,
        responses={
            200: SecureConnectionTestSerializer,
            503: OpenApiResponse(
                response=ErrorResponseSerializer, description="The connection service is unavailable."
            ),
        },
        description="Check whether the project has an active secure connection.",
    )
    @action(methods=["GET"], detail=False)
    def test(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            connection_status = api.get_status(self.team_id)
        except SecureConnectionServiceError as error:
            self._handle_service_error(error)
        success = connection_status.connection_state == "connected"
        detail = (
            "The connection is active."
            if success
            else "No active connection was found. Start your connection proxy and try again."
        )
        return Response(SecureConnectionTestSerializer({"success": success, "detail": detail}).data)

    @extend_schema(
        request=SecureConnectionApprovalSerializer,
        responses={200: SecureConnectionApprovalsSerializer},
        description="List or update the secure connections approved for CDP destinations.",
    )
    @action(methods=["GET", "POST"], detail=False)
    def cdp_approvals(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if request.method == "POST":
            serializer = SecureConnectionApprovalSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            connection_id = str(serializer.validated_data["connection_id"])
            approved = serializer.validated_data["approved"]
            if approved:
                try:
                    connection_status = api.get_status(self.team_id)
                except SecureConnectionServiceError as error:
                    self._handle_service_error(error)
                connection = next((item for item in connection_status.connections if item.id == connection_id), None)
                if connection is None:
                    raise ValidationError({"connection_id": "This active connection is not available to this project."})
                if connection.selector_kind != "hostname":
                    raise ValidationError({"connection_id": "CDP can only use hostname-routed HTTP services."})
            else:
                approvals = api.get_cdp_approved_connections(self.team_id)
                existing = approvals.get(connection_id)
                if existing is None:
                    raise ValidationError({"connection_id": "This connection is not approved for CDP."})
                connection = SecureConnection(
                    id=connection_id,
                    name=existing["name"],
                    connection_type="",
                    connection_status="",
                    selector_kind=existing["selector_kind"],
                    selector=existing["selector"],
                )
            api.set_cdp_connection_approval(self.team_id, connection, approved=approved)

        return Response(
            SecureConnectionApprovalsSerializer(
                {"cdp_approved_connections": api.get_cdp_approved_connections(self.team_id)}
            ).data
        )
