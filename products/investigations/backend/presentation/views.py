from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import NotAuthenticated, NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api
from ..facade.contracts import InvestigationConflict, InvestigationNotFound
from .serializers import (
    InvestigationCreateSerializer,
    InvestigationErrorSerializer,
    InvestigationListQuerySerializer,
    InvestigationListSerializer,
    InvestigationSerializer,
    InvestigationUpdateSerializer,
)


class InvestigationViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "investigation"
    requires_resource_level_access = True
    serializer_class = InvestigationSerializer
    pagination_class = None
    lookup_value_regex = "[0-9a-f-]{36}"

    @extend_schema(parameters=[InvestigationListQuerySerializer], responses={200: InvestigationListSerializer})
    def list(self, request: Request, **kwargs) -> Response:
        query = InvestigationListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        results, count = api.list_investigations(self.team_id, **query.validated_data)
        return Response(InvestigationListSerializer({"results": results, "count": count}).data)

    @extend_schema(responses={200: InvestigationSerializer, 404: InvestigationErrorSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        try:
            investigation = api.get_investigation(self.team_id, UUID(pk))
        except (InvestigationNotFound, ValueError) as exc:
            raise NotFound("Investigation not found.") from exc
        return Response(InvestigationSerializer(investigation).data)

    @extend_schema(request=InvestigationCreateSerializer, responses={201: InvestigationSerializer})
    def create(self, request: Request, **kwargs) -> Response:
        if request.user.pk is None:
            raise NotAuthenticated()
        serializer = InvestigationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        investigation = api.create_investigation(self.team_id, request.user.pk, serializer.validated_data["document"])
        return Response(InvestigationSerializer(investigation).data, status=201)

    @extend_schema(
        request=InvestigationUpdateSerializer,
        responses={200: InvestigationSerializer, 409: InvestigationErrorSerializer},
    )
    def partial_update(self, request: Request, pk: str, **kwargs) -> Response:
        serializer = InvestigationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            investigation = api.update_investigation(
                self.team_id,
                UUID(pk),
                document=serializer.validated_data.get("document"),
                revision=serializer.validated_data["revision"],
                deleted=serializer.validated_data["deleted"],
            )
        except (InvestigationNotFound, ValueError) as exc:
            raise NotFound("Investigation not found.") from exc
        except InvestigationConflict:
            return Response(
                {
                    "detail": "Someone saved a newer version. Your changes are still here. Save a copy or reload the latest version."
                },
                status=409,
            )
        return Response(InvestigationSerializer(investigation).data)
