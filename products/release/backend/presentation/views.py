"""
DRF views for release.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

from typing import Any
from uuid import UUID

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import TypedRequest, validated_request
from posthog.api.pagination import FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api, contracts
from .serializers import ReleaseSerializer, UpdateReleaseSerializer, WriteReleaseSerializer


class ReleaseViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "feature_flag"
    requires_resource_level_access = True
    serializer_class = ReleaseSerializer
    pagination_class = FacadeLimitOffsetPagination
    path_parameters = {"pk": UUID}

    @extend_schema(responses={200: ReleaseSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        """List the releases of the project, oldest first."""
        return facade_page_response(
            self, lambda page: api.list_page(self.team_id, page), serializer_class=ReleaseSerializer
        )

    @validated_request(
        request_serializer=WriteReleaseSerializer,
        responses={201: OpenApiResponse(response=ReleaseSerializer)},
        include_serializer_context=True,
    )
    def create(self, request: TypedRequest[dict[str, Any]], **kwargs) -> Response:
        """Create a release."""
        try:
            dto = api.create(contracts.CreateReleaseInput(team_id=self.team_id, **request.validated_data))
        except api.UnknownFeatureFlagsError as error:
            raise ValidationError({"feature_flag_ids": f"These flags do not exist in this project: {error.flag_ids}"})
        return Response(ReleaseSerializer(dto).data, status=status.HTTP_201_CREATED)

    @validated_request(
        request_serializer=UpdateReleaseSerializer,
        responses={200: OpenApiResponse(response=ReleaseSerializer)},
        include_serializer_context=True,
    )
    def partial_update(self, request: TypedRequest[dict[str, Any]], pk: UUID, **kwargs) -> Response:
        """Change the name, description, owner or linked flags of a release."""
        try:
            dto = api.update(self.team_id, pk, request.validated_data)
        except api.ReleaseNotFoundError:
            raise NotFound("Release not found.")
        except api.UnknownFeatureFlagsError as error:
            raise ValidationError({"feature_flag_ids": f"These flags do not exist in this project: {error.flag_ids}"})
        return Response(ReleaseSerializer(dto).data)

    @extend_schema(responses={204: None})
    def destroy(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Delete a release. Its flags, experiments and early access features stay."""
        api.delete(self.team_id, pk)
        return Response(status=status.HTTP_204_NO_CONTENT)
