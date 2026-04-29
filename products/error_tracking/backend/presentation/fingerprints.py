from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.facade.api import get_fingerprint, list_fingerprints


class ErrorTrackingFingerprintSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    fingerprint = serializers.CharField(read_only=True)
    issue_id = serializers.UUIDField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


@extend_schema(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingFingerprintViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions: list[str] = []
    serializer_class = ErrorTrackingFingerprintSerializer

    def list(self, request, *args, **kwargs):
        issue_id: UUID | None = None
        issue_id_param = self.request.GET.get("issue_id")
        if issue_id_param:
            try:
                issue_id = UUID(issue_id_param)
            except ValueError as error:
                raise ValidationError("issue_id must be a valid UUID") from error

        fingerprints = list_fingerprints(team_id=self.team.id, issue_id=issue_id)

        page = self.paginate_queryset(fingerprints)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(fingerprints, many=True)
        return Response(serializer.data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description="Fingerprint ID.",
            )
        ]
    )
    def retrieve(self, request, *args, **kwargs):
        try:
            fingerprint_id = UUID(str(kwargs["pk"]))
        except ValueError as error:
            raise ValidationError("Invalid fingerprint id") from error

        fingerprint = get_fingerprint(team_id=self.team.id, fingerprint_id=fingerprint_id)
        if fingerprint is None:
            raise NotFound("Fingerprint not found")

        serializer = self.get_serializer(fingerprint)
        return Response(serializer.data)
