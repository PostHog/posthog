"""
DRF views for release.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api, contracts
from .serializers import ReleaseSerializer, WriteReleaseSerializer


class ReleaseViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "feature_flag"
    serializer_class = ReleaseSerializer

    @extend_schema(responses={200: ReleaseSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        return Response(ReleaseSerializer(api.list_all(), many=True).data)

    @extend_schema(request=WriteReleaseSerializer, responses={201: ReleaseSerializer})
    def create(self, request: Request, **kwargs) -> Response:
        serializer = WriteReleaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dto = api.create(contracts.CreateReleaseInput(team_id=self.team_id, **serializer.validated_data))
        return Response(ReleaseSerializer(dto).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=WriteReleaseSerializer, responses={200: ReleaseSerializer})
    def partial_update(self, request: Request, pk: str, **kwargs) -> Response:
        serializer = WriteReleaseSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(ReleaseSerializer(api.update(pk, serializer.validated_data)).data)

    @extend_schema(responses={204: None})
    def destroy(self, request: Request, pk: str, **kwargs) -> Response:
        api.delete(pk)
        return Response(status=status.HTTP_204_NO_CONTENT)
