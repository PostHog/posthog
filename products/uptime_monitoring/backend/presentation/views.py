from typing import Any, cast
from uuid import UUID

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import TypedRequest, validated_request
from posthog.api.pagination import PrecountedLimitOffsetPagination
from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api
from ..facade.contracts import CreateUptimeMonitorInput, UpdateUptimeMonitorInput, UptimeMonitorNotFoundError
from .serializers import CreateUptimeMonitorInputSerializer, UpdateUptimeMonitorInputSerializer, UptimeMonitorSerializer

_ID_PARAMETER = OpenApiParameter("id", OpenApiTypes.UUID, OpenApiParameter.PATH)
DEFAULT_PAGE_SIZE = 100


def _parse_id(pk: str) -> UUID:
    try:
        return UUID(pk)
    except ValueError:
        raise NotFound()


class UptimeMonitorViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """URLs that PostHog checks on a schedule."""

    # Session access only until the product is released and has its own API scope.
    scope_object = "INTERNAL"
    pagination_class = PrecountedLimitOffsetPagination

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if not api.is_enabled(self.team_id):
            raise NotFound()

    @extend_schema(responses={200: UptimeMonitorSerializer(many=True)})
    def list(self, request: Request, **kwargs: Any) -> Response:
        """List the project's uptime monitors, newest first."""
        paginator = cast(PrecountedLimitOffsetPagination, self.paginator)
        monitors, count = api.list_monitors(
            self.team_id, limit=paginator.get_limit(request) or DEFAULT_PAGE_SIZE, offset=paginator.get_offset(request)
        )
        paginator.set_count(count)
        page = self.paginate_queryset(monitors)
        return self.get_paginated_response(UptimeMonitorSerializer(instance=page, many=True).data)

    @validated_request(
        request_serializer=CreateUptimeMonitorInputSerializer,
        responses={201: OpenApiResponse(response=UptimeMonitorSerializer)},
    )
    def create(self, request: TypedRequest[CreateUptimeMonitorInput], **kwargs: Any) -> Response:
        """Create an uptime monitor."""
        monitor = api.create_monitor(self.team_id, request.user.id, request.validated_data)
        return Response(UptimeMonitorSerializer(instance=monitor).data, status=status.HTTP_201_CREATED)

    @extend_schema(parameters=[_ID_PARAMETER], responses={200: UptimeMonitorSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs: Any) -> Response:
        """Get an uptime monitor."""
        try:
            monitor = api.get_monitor(self.team_id, _parse_id(pk))
        except UptimeMonitorNotFoundError:
            raise NotFound()
        return Response(UptimeMonitorSerializer(instance=monitor).data)

    @extend_schema(parameters=[_ID_PARAMETER])
    @validated_request(
        request_serializer=UpdateUptimeMonitorInputSerializer,
        responses={200: OpenApiResponse(response=UptimeMonitorSerializer)},
    )
    def partial_update(self, request: TypedRequest[UpdateUptimeMonitorInput], pk: str, **kwargs: Any) -> Response:
        """Change some fields of an uptime monitor."""
        try:
            monitor = api.update_monitor(self.team_id, _parse_id(pk), request.validated_data)
        except UptimeMonitorNotFoundError:
            raise NotFound()
        return Response(UptimeMonitorSerializer(instance=monitor).data)

    @extend_schema(parameters=[_ID_PARAMETER], responses={204: None})
    def destroy(self, request: Request, pk: str, **kwargs: Any) -> Response:
        """Delete an uptime monitor."""
        try:
            api.delete_monitor(self.team_id, _parse_id(pk))
        except UptimeMonitorNotFoundError:
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)
