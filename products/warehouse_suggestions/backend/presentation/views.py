"""DRF views for warehouse_suggestions."""

from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.exceptions import Conflict
from posthog.models import User
from posthog.permissions import APIScopePermission, TeamMemberAccessPermission
from posthog.utils import UUID_REGEX

from ..facade import api
from ..facade.api import is_warehouse_suggestions_enabled
from ..facade.contracts import (
    SubjectEditAccessRequiredError,
    Suggestion,
    SuggestionAlreadyDecidedError,
    SuggestionNotFoundError,
    SuggestionPage,
)
from ..facade.enums import WarehouseSuggestionKind, WarehouseSuggestionStatus, WarehouseSuggestionSubjectKind
from .serializers import (
    DismissWarehouseSuggestionSerializer,
    WarehouseSuggestionListQuerySerializer,
    WarehouseSuggestionSerializer,
)

DEFAULT_PAGE_SIZE = 100
EDIT_ACCESS_REQUIRED = {
    WarehouseSuggestionSubjectKind.SAVED_QUERY: "You need edit access to this view to change its suggestion.",
    WarehouseSuggestionSubjectKind.TABLE: "You need edit access to this table to change its suggestion.",
}


class SuggestionPagination(LimitOffsetPagination):
    default_limit = DEFAULT_PAGE_SIZE
    max_limit = DEFAULT_PAGE_SIZE

    def paginate(self, request: Request, fetch_page: Callable[[int, int], SuggestionPage]) -> Response:
        self.request = request
        self.limit = self.get_limit(request) or DEFAULT_PAGE_SIZE
        self.offset = self.get_offset(request)
        page = fetch_page(self.limit, self.offset)
        self.count = page.count
        return self.get_paginated_response(WarehouseSuggestionSerializer(page.results, many=True).data)


class ProjectAccessPermission(BasePermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        viewset = cast("WarehouseSuggestionViewSet", view)
        return viewset.user_access_control.check_access_level_for_object(viewset.team, required_level="member")


class WarehouseSuggestionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "warehouse_objects"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["dismiss", "resume"]
    pagination_class = SuggestionPagination
    lookup_value_regex = UUID_REGEX

    def dangerously_get_permissions(self) -> list[BasePermission]:
        return [IsAuthenticated(), APIScopePermission(), TeamMemberAccessPermission(), ProjectAccessPermission()]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if not is_warehouse_suggestions_enabled(self.team):
            raise PermissionDenied("Warehouse suggestions are not enabled for this project.")

    @validated_request(
        query_serializer=WarehouseSuggestionListQuerySerializer,
        responses={200: OpenApiResponse(response=WarehouseSuggestionSerializer(many=True))},
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        kind = request.validated_query_data.get("kind")
        status = request.validated_query_data.get("status")
        return cast(SuggestionPagination, self.paginator).paginate(
            request,
            lambda limit, offset: api.list_suggestions(
                self.team_id,
                self.user_access_control,
                kind=WarehouseSuggestionKind(kind) if kind else None,
                status=WarehouseSuggestionStatus(status) if status else None,
                limit=limit,
                offset=offset,
            ),
        )

    @extend_schema(responses={200: WarehouseSuggestionSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs: Any) -> Response:
        return self._respond(lambda: api.get_suggestion(self.team_id, self.user_access_control, UUID(pk)))

    @validated_request(
        request_serializer=DismissWarehouseSuggestionSerializer,
        responses={200: OpenApiResponse(response=WarehouseSuggestionSerializer)},
    )
    @action(detail=True, methods=["post"])
    def dismiss(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        return self._respond(
            lambda: api.dismiss_suggestion(
                self.team_id,
                self.user_access_control,
                UUID(pk),
                user_id=cast(User, request.user).id,
                reason=request.validated_data["reason"],
                note=request.validated_data.get("note") or None,
            )
        )

    @extend_schema(request=None, responses={200: WarehouseSuggestionSerializer})
    @action(detail=True, methods=["post"])
    def resume(self, request: Request, pk: str, **kwargs: Any) -> Response:
        return self._respond(
            lambda: api.resume_suggestion(
                self.team_id, self.user_access_control, UUID(pk), user_id=cast(User, request.user).id
            )
        )

    def _respond(self, decide_or_read: Callable[[], Suggestion]) -> Response:
        try:
            return Response(WarehouseSuggestionSerializer(decide_or_read()).data)
        except SuggestionNotFoundError:
            raise NotFound()
        except SubjectEditAccessRequiredError as error:
            raise PermissionDenied(EDIT_ACCESS_REQUIRED[error.subject_kind])
        except SuggestionAlreadyDecidedError as error:
            raise Conflict(str(error))
