import logging
from uuid import UUID

from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.facade import types as contracts
from products.error_tracking.backend.facade.api import (
    ExternalReferenceValidationError,
    create_external_reference,
    get_external_reference,
    is_supported_external_issue_provider,
    list_external_references,
)

logger = logging.getLogger(__name__)


@extend_schema_serializer(component_name="ErrorTrackingExternalReferenceIntegrationResult")
class ErrorTrackingExternalReferenceIntegrationSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    kind = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)


@extend_schema_serializer(component_name="ErrorTrackingExternalReferenceResult")
class ErrorTrackingExternalReferenceSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    integration = ErrorTrackingExternalReferenceIntegrationSerializer(read_only=True)
    integration_id = serializers.IntegerField(write_only=True)
    config = serializers.JSONField(write_only=True)
    issue = serializers.UUIDField(write_only=True)
    external_url = serializers.SerializerMethodField()

    def get_external_url(self, reference: contracts.ErrorTrackingExternalReference) -> str:
        if reference.external_url:
            return reference.external_url

        if is_supported_external_issue_provider(reference.integration.kind):
            raise ValidationError("Missing required external context fields")

        raise ValidationError("Provider not supported")


@extend_schema(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingExternalReferenceViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    serializer_class = ErrorTrackingExternalReferenceSerializer

    def list(self, request, *args, **kwargs):
        references = list_external_references(team_id=self.team.id)

        page = self.paginate_queryset(references)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(references, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        try:
            reference_id = UUID(str(kwargs["pk"]))
        except ValueError as error:
            raise ValidationError("Invalid external reference id") from error

        reference = get_external_reference(reference_id=reference_id, team_id=self.team.id)
        if reference is None:
            raise NotFound("External reference not found")

        serializer = self.get_serializer(reference)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        issue_id = serializer.validated_data["issue"]
        if not isinstance(issue_id, UUID):
            issue_id = UUID(str(issue_id))

        try:
            reference = create_external_reference(
                team_id=self.team.id,
                issue_id=issue_id,
                integration_id=serializer.validated_data["integration_id"],
                config=serializer.validated_data["config"],
            )
        except ExternalReferenceValidationError as error:
            logger.warning("Failed to create external reference", exc_info=error)
            raise ValidationError("Invalid external reference configuration") from error

        response_serializer = self.get_serializer(reference)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)
