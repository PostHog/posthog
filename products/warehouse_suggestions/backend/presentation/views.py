"""DRF views for warehouse_suggestions."""

from collections.abc import Callable
from datetime import timedelta
from functools import cached_property
from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.exceptions import Conflict
from posthog.helpers.impersonation import is_impersonated
from posthog.models import User
from posthog.permissions import APIScopePermission, TeamMemberAccessPermission, get_authenticator_scopes
from posthog.scopes import scopes_not_covered
from posthog.utils import UUID_REGEX

from ..facade import api
from ..facade.api import is_warehouse_suggestions_enabled
from ..facade.contracts import (
    AcceptFailedError,
    CatalogEditAccessRequiredError,
    RefreshIntervalRefusedError,
    SubjectAlreadyCertifiedError,
    SubjectEditAccessRequiredError,
    Suggestion,
    SuggestionAlreadyDecidedError,
    SuggestionNotFoundError,
    SuggestionPage,
    SuggestionSubjectGoneError,
)
from ..facade.enums import WarehouseSuggestionKind, WarehouseSuggestionStatus, WarehouseSuggestionSubjectKind
from .serializers import (
    AcceptWarehouseSuggestionSerializer,
    DismissWarehouseSuggestionSerializer,
    WarehouseSuggestionListQuerySerializer,
    WarehouseSuggestionSerializer,
    WarehouseSuggestionStatusSerializer,
)

DEFAULT_PAGE_SIZE = 100
EDIT_ACCESS_REQUIRED = {
    WarehouseSuggestionSubjectKind.SAVED_QUERY: "You need edit access to this view to change its suggestion.",
    WarehouseSuggestionSubjectKind.TABLE: "You need edit access to this table to change its suggestion.",
}


SUBJECT_GONE = {
    WarehouseSuggestionSubjectKind.SAVED_QUERY: "This view no longer exists.",
    WarehouseSuggestionSubjectKind.TABLE: "This table no longer exists.",
}
ALREADY_CERTIFIED = {
    WarehouseSuggestionSubjectKind.SAVED_QUERY: "This view already has a certification.",
    WarehouseSuggestionSubjectKind.TABLE: "This table already has a certification.",
}
CATALOG_EDIT_ACCESS_REQUIRED = "You need edit access to the data catalog to accept this suggestion."
ACCEPT_SCOPES = ["data_catalog_approval:write", "warehouse_view:write"]
SUBJECT_SCOPE_OBJECTS = {
    WarehouseSuggestionSubjectKind.SAVED_QUERY: "warehouse_view",
    WarehouseSuggestionSubjectKind.TABLE: "warehouse_table",
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
    scope_object_read_actions = ["list", "retrieve", "status"]
    scope_object_write_actions = ["accept", "dismiss", "resume"]
    pagination_class = SuggestionPagination
    lookup_value_regex = UUID_REGEX

    def dangerously_get_permissions(self) -> list[BasePermission]:
        return [IsAuthenticated(), APIScopePermission(), TeamMemberAccessPermission(), ProjectAccessPermission()]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if not is_warehouse_suggestions_enabled(self.team):
            raise PermissionDenied("Warehouse suggestions are not enabled for this project.")

    def dangerously_get_required_scopes(self, request: Request, view: APIView) -> list[str] | None:
        subject_scope = next(iter(self._subject_scopes_on_token.values()), f"{self.scope_object}:{self._scope_level}")
        return [subject_scope, *ACCEPT_SCOPES] if self.action == "accept" else [subject_scope]

    @property
    def _scope_level(self) -> str:
        return "write" if self.action in self.scope_object_write_actions else "read"

    @cached_property
    def _subject_scopes_on_token(self) -> dict[WarehouseSuggestionSubjectKind, str]:
        held = get_authenticator_scopes(self.request.successful_authenticator) or ()
        reaching: dict[WarehouseSuggestionSubjectKind, str] = {}
        for subject_kind, scope_object in SUBJECT_SCOPE_OBJECTS.items():
            candidates = (f"{self.scope_object}:{self._scope_level}", f"{scope_object}:{self._scope_level}")
            held_scope = next((scope for scope in candidates if not scopes_not_covered(held, [scope])), None)
            if held_scope is not None:
                reaching[subject_kind] = held_scope
        return reaching

    @cached_property
    def _subject_kinds(self) -> frozenset[WarehouseSuggestionSubjectKind]:
        held = get_authenticator_scopes(self.request.successful_authenticator)
        if held is None or "*" in held:
            return frozenset(WarehouseSuggestionSubjectKind)
        return frozenset(self._subject_scopes_on_token)

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
                subject_id=request.validated_query_data.get("subject_id"),
                subject_kinds=self._subject_kinds,
                limit=limit,
                offset=offset,
            ),
        )

    @extend_schema(responses={200: WarehouseSuggestionStatusSerializer})
    @action(detail=False, methods=["get"], pagination_class=None)
    def status(self, request: Request, **kwargs: Any) -> Response:
        return Response(WarehouseSuggestionStatusSerializer(api.suggestion_status(self.team_id)).data)

    @extend_schema(responses={200: WarehouseSuggestionSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs: Any) -> Response:
        return self._respond(
            lambda: api.get_suggestion(
                self.team_id, self.user_access_control, UUID(pk), subject_kinds=self._subject_kinds
            )
        )

    @validated_request(
        request_serializer=DismissWarehouseSuggestionSerializer,
        responses={200: OpenApiResponse(response=WarehouseSuggestionSerializer)},
    )
    @action(detail=True, methods=["post"])
    def dismiss(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        return self._respond(
            lambda: api.dismiss_suggestion(
                self.team,
                self.user_access_control,
                UUID(pk),
                user=cast(User, request.user),
                reason=request.validated_data["reason"],
                note=request.validated_data.get("note") or None,
                subject_kinds=self._subject_kinds,
            )
        )

    @validated_request(
        request_serializer=AcceptWarehouseSuggestionSerializer,
        responses={200: OpenApiResponse(response=WarehouseSuggestionSerializer)},
    )
    @action(detail=True, methods=["post"])
    def accept(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        interval_seconds = request.validated_data.get("refresh_interval_seconds")
        return self._respond(
            lambda: api.accept_suggestion(
                self.team,
                self.user_access_control,
                UUID(pk),
                user=cast(User, request.user),
                refresh_interval=timedelta(seconds=interval_seconds) if interval_seconds else None,
                was_impersonated=is_impersonated(request),
                subject_kinds=self._subject_kinds,
            )
        )

    @extend_schema(request=None, responses={200: WarehouseSuggestionSerializer})
    @action(detail=True, methods=["post"])
    def resume(self, request: Request, pk: str, **kwargs: Any) -> Response:
        return self._respond(
            lambda: api.resume_suggestion(
                self.team,
                self.user_access_control,
                UUID(pk),
                user=cast(User, request.user),
                subject_kinds=self._subject_kinds,
            )
        )

    def _respond(self, decide_or_read: Callable[[], Suggestion]) -> Response:
        try:
            return Response(WarehouseSuggestionSerializer(decide_or_read()).data)
        except SuggestionNotFoundError:
            raise NotFound()
        except SubjectEditAccessRequiredError as error:
            raise PermissionDenied(EDIT_ACCESS_REQUIRED[error.subject_kind])
        except CatalogEditAccessRequiredError:
            raise PermissionDenied(CATALOG_EDIT_ACCESS_REQUIRED)
        except SuggestionAlreadyDecidedError as error:
            raise Conflict(str(error))
        except SubjectAlreadyCertifiedError as error:
            raise Conflict(ALREADY_CERTIFIED[error.subject_kind])
        except SuggestionSubjectGoneError as error:
            raise ValidationError({"subject_id": SUBJECT_GONE[error.subject_kind]})
        except RefreshIntervalRefusedError as error:
            raise ValidationError({"refresh_interval_seconds": str(error)})
        except AcceptFailedError as error:
            raise APIException(str(error))
