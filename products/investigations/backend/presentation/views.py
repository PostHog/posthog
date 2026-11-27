from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import NotAuthenticated, NotFound
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.team import Team
from posthog.permissions import credential_admits_team, is_service_auth, request_subject
from posthog.rate_limit import (
    InvestigationSearchRateThrottle,
    InvestigationWriteBurstRateThrottle,
    InvestigationWriteSustainedRateThrottle,
)

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import Resource
from products.authorization.backend.facade.enums import Action

from ..facade import api
from ..facade.contracts import InvestigationConflict, InvestigationNotFound, SavedInvestigation
from .serializers import (
    InvestigationCreateSerializer,
    InvestigationErrorSerializer,
    InvestigationListQuerySerializer,
    InvestigationListSerializer,
    InvestigationSerializer,
    InvestigationUpdateSerializer,
)


class InvestigationOwningProjectPermission(BasePermission):
    message = "You don't have access to investigations in this project."

    def has_permission(self, request: Request, view: "InvestigationViewSet") -> bool:
        project_id = view.resource_access_team.pk
        if project_id == view.team_id:
            return True
        if is_service_auth(request) or not credential_admits_team(request, project_id, view.team.organization_id):
            return False
        return authorization.check(
            resource=Resource.project(project_id), action=Action.VIEW, subject=request_subject(request)
        )


class InvestigationViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "investigation"
    requires_resource_level_access = True
    permission_classes = [InvestigationOwningProjectPermission]
    serializer_class = InvestigationSerializer
    pagination_class = None
    lookup_value_regex = "[0-9a-f-]{36}"

    @property
    def resource_access_team(self) -> Team:
        return self.team.parent_team or self.team

    def get_throttles(self) -> list[BaseThrottle]:
        throttles = super().get_throttles()
        if self.action in {"create", "partial_update"}:
            throttles.extend([InvestigationWriteBurstRateThrottle(), InvestigationWriteSustainedRateThrottle()])
        elif self.action == "list" and self.request.query_params.get("search", "").strip():
            throttles.append(InvestigationSearchRateThrottle())
        return throttles

    def read_object(self) -> SavedInvestigation | None:
        try:
            return api.get_investigation(self.resource_access_team.pk, UUID(self.kwargs["pk"]))
        except (InvestigationNotFound, ValueError):
            return None

    def object_access_ref(self, record: SavedInvestigation) -> ObjectAccessRef:
        return ObjectAccessRef(
            resource="investigation",
            id=str(record.id),
            team_id=self.resource_access_team.pk,
            created_by_id=record.created_by,
        )

    @extend_schema(parameters=[InvestigationListQuerySerializer], responses={200: InvestigationListSerializer})
    def list(self, request: Request, **kwargs) -> Response:
        query = InvestigationListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        service = is_service_auth(request)
        if not service and request.user.pk is None:
            raise NotAuthenticated()
        results, count = api.list_investigations(
            self.team_id,
            user_id=None if service else request.user.pk,
            **query.validated_data,
        )
        return Response(InvestigationListSerializer({"results": results, "count": count}).data)

    @extend_schema(responses={200: InvestigationSerializer, 404: InvestigationErrorSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        return Response(InvestigationSerializer(self.get_object()).data)

    @extend_schema(request=InvestigationCreateSerializer, responses={201: InvestigationSerializer})
    def create(self, request: Request, **kwargs) -> Response:
        if request.user.pk is None:
            raise NotAuthenticated()
        serializer = InvestigationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        investigation = api.create_investigation(
            self.resource_access_team.pk, request.user.pk, serializer.validated_data["document"]
        )
        return Response(InvestigationSerializer(investigation).data, status=201)

    @extend_schema(
        request=InvestigationUpdateSerializer,
        responses={200: InvestigationSerializer, 409: InvestigationErrorSerializer},
    )
    def partial_update(self, request: Request, pk: str, **kwargs) -> Response:
        record = self.get_object()
        serializer = InvestigationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            investigation = api.update_investigation(
                self.resource_access_team.pk,
                record.id,
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
