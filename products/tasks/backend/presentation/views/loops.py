import json

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, ProjectSecretAPIKeyAuthentication
from posthog.permissions import APIScopePermission
from posthog.rate_limit import PersonalOrProjectSecretApiKeyRateThrottle, ProjectSecretApiKeyTeamRateThrottle

from products.tasks.backend.facade import (
    access as tasks_access,
    loops as loops_facade,
)
from products.tasks.backend.presentation.serializers_loops import (
    LoopFireRunSerializer,
    LoopPreviewRequestSerializer,
    LoopPreviewSerializer,
    LoopRunPageSerializer,
    LoopRunsQuerySerializer,
    LoopSerializer,
    LoopWriteSerializer,
)

MAX_LOOP_TRIGGER_PAYLOAD_BYTES = 64 * 1024


class LoopsPagination(LimitOffsetPagination):
    default_limit = 50
    max_limit = 100


class LoopTriggerBurstThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "loop_trigger_burst"
    rate = "60/minute"


class LoopTriggerSustainedThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "loop_trigger_sustained"
    rate = "1000/hour"


class LoopTriggerProjectSecretApiKeyTeamBurstThrottle(ProjectSecretApiKeyTeamRateThrottle):
    """Per-team aggregate burst budget across all of a project's PSAKs firing loops."""

    scope = "loop_trigger_psak_team_burst"
    rate = "60/minute"


class LoopTriggerProjectSecretApiKeyTeamSustainedThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "loop_trigger_psak_team_sustained"
    rate = "1000/hour"


class HasLoopsAccess(BasePermission):
    """Gate every Loops endpoint on `has_loops_access` (tasks access plus the `loops` flag).

    Exempts `trigger`: that action authenticates a project-scoped service credential (PSAK),
    not a real user, so the person-targeted `loops` flag doesn't apply — `loop:write` scope and
    the trigger throttles gate it instead.
    """

    message = "This project does not have access to Loops."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if getattr(view, "action", None) == "trigger":
            return True
        if not request.user.is_authenticated:
            return False
        return tasks_access.has_loops_access(request.user, view.team)  # type: ignore[attr-defined]


def _idempotency_key(request) -> str | None:
    return request.META.get("HTTP_IDEMPOTENCY_KEY") or None


def _content_length(request) -> int:
    try:
        return int(request.META.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        return 0


@extend_schema(tags=["loops"])
class LoopViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """API for managing loops — named, cloud-executed agent automations triggered by
    schedule, GitHub events or authenticated API calls. See `products/tasks/docs/LOOPS.md`."""

    authentication_classes = [
        ProjectSecretAPIKeyAuthentication,
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, HasLoopsAccess, APIScopePermission]
    scope_object = "loop"
    # Only the external-fire endpoint accepts a project secret API key; everything else
    # (CRUD, manual run, run history, preview) stays session/PAT/OAuth-only.
    psak_allowed_actions = ["trigger"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    pagination_class = LoopsPagination
    # Fallback for drf-spectacular introspection only; every action declares its own
    # request/response schema via @validated_request / @extend_schema.
    serializer_class = LoopSerializer

    def _user_id(self) -> int | None:
        return getattr(self.request.user, "id", None)

    def _write_serializer(self, data, *, partial: bool = False) -> LoopWriteSerializer:
        serializer = LoopWriteSerializer(
            data=data,
            partial=partial,
            context={"team": self.team, "team_id": self.team.id, "user_id": self._user_id()},
        )
        serializer.is_valid(raise_exception=True)
        return serializer

    def get_throttles(self):
        if self.action == "trigger":
            return [
                LoopTriggerBurstThrottle(),
                LoopTriggerSustainedThrottle(),
                LoopTriggerProjectSecretApiKeyTeamBurstThrottle(),
                LoopTriggerProjectSecretApiKeyTeamSustainedThrottle(),
            ]
        return super().get_throttles()

    @extend_schema(
        summary="List loops",
        description="List loops visible to the caller: personal loops they own, plus every team loop.",
        responses={200: LoopSerializer(many=True)},
    )
    def list(self, request, **kwargs):
        loops = loops_facade.list_loops(self.team_id, request.user)
        page = self.paginate_queryset(loops)
        if page is not None:
            return self.get_paginated_response(LoopSerializer(page, many=True).data)
        return Response(LoopSerializer(loops, many=True).data)

    @extend_schema(
        summary="Get a loop", responses={200: LoopSerializer, 404: OpenApiResponse(description="Loop not found")}
    )
    def retrieve(self, request, pk=None, **kwargs):
        loop = loops_facade.get_loop(pk, self.team_id, request.user)
        if loop is None:
            raise NotFound()
        return Response(LoopSerializer(loop).data)

    @extend_schema(summary="Create a loop", request=LoopWriteSerializer, responses={201: LoopSerializer})
    def create(self, request, **kwargs):
        serializer = self._write_serializer(request.data)
        loop = loops_facade.create_loop(self.team_id, request.user, dict(serializer.validated_data))
        return Response(LoopSerializer(loop).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Update a loop",
        description=(
            "Partial update. Identity-bearing fields (instructions, repositories, connectors, "
            "behaviors, model config, triggers) are owner-only on team loops; name, description, "
            "notifications and enable/pause are editable by any team member."
        ),
        request=LoopWriteSerializer,
        responses={
            200: LoopSerializer,
            403: OpenApiResponse(description="Not permitted to change these fields"),
            404: OpenApiResponse(description="Loop not found"),
        },
    )
    def partial_update(self, request, pk=None, **kwargs):
        serializer = self._write_serializer(request.data, partial=True)
        try:
            loop = loops_facade.update_loop(pk, self.team_id, request.user, dict(serializer.validated_data))
        except loops_facade.LoopPermissionError as exc:
            raise PermissionDenied(str(exc))
        if loop is None:
            raise NotFound()
        return Response(LoopSerializer(loop).data)

    @extend_schema(
        summary="Delete a loop",
        description="Soft delete. Pauses every trigger's schedule. Owner or a project admin only.",
        responses={
            204: None,
            403: OpenApiResponse(description="Not permitted to delete this loop"),
            404: OpenApiResponse(description="Loop not found"),
        },
    )
    def destroy(self, request, pk=None, **kwargs):
        try:
            deleted = loops_facade.soft_delete_loop(pk, self.team_id, request.user)
        except loops_facade.LoopPermissionError as exc:
            raise PermissionDenied(str(exc))
        if not deleted:
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Run a loop manually",
        description="Manual fire from the UI. Owner-only for personal loops; any team member for team loops.",
        request=None,
        responses={
            200: LoopFireRunSerializer,
            403: OpenApiResponse(description="Not permitted to run this loop"),
            404: OpenApiResponse(description="Loop not found"),
        },
    )
    @action(detail=True, methods=["post"], url_path="run", required_scopes=["loop:write"])
    def run(self, request, pk=None, **kwargs):
        try:
            result = loops_facade.fire_loop_manual(
                pk, self.team_id, request.user, idempotency_key=_idempotency_key(request)
            )
        except loops_facade.LoopPermissionError as exc:
            raise PermissionDenied(str(exc))
        if result is None:
            raise NotFound()
        return Response(LoopFireRunSerializer(result).data)

    @extend_schema(
        summary="Fire a loop externally",
        description=(
            "Authenticated POST trigger for `type=api` triggers. Project secret API key auth "
            "(`loop:write` scope), project-wide. Request body (JSON, capped at 64 KB) becomes run "
            "context. Send an `Idempotency-Key` header to dedupe retries."
        ),
        request=OpenApiTypes.OBJECT,
        responses={
            200: LoopFireRunSerializer,
            404: OpenApiResponse(description="Loop not found"),
            413: OpenApiResponse(description="Request body exceeds 64 KB"),
        },
    )
    @action(detail=True, methods=["post"], url_path="trigger", required_scopes=["loop:write"])
    def trigger(self, request, pk=None, **kwargs):
        # Content-Length, not `request.body`: permission checks upstream (`view.team` via
        # `AccessControlPermission`) already consume the request stream through `request.POST`,
        # so `request.body` raises `RawPostDataException` by the time this handler runs.
        if _content_length(request) > MAX_LOOP_TRIGGER_PAYLOAD_BYTES:
            return Response({"detail": "Request body exceeds 64 KB."}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        payload = request.data if isinstance(request.data, dict) else {}
        # Content-Length can be absent (chunked transfer, ASGI), so the parsed payload is the
        # authoritative cap; parse pressure stays bounded by DATA_UPLOAD_MAX_MEMORY_SIZE.
        payload_size = len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
        if payload_size > MAX_LOOP_TRIGGER_PAYLOAD_BYTES:
            return Response({"detail": "Request body exceeds 64 KB."}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        result = loops_facade.fire_loop_api(pk, self.team_id, payload, idempotency_key=_idempotency_key(request))
        if result is None:
            raise NotFound()
        return Response(LoopFireRunSerializer(result).data)

    @validated_request(
        query_serializer=LoopRunsQuerySerializer,
        responses={
            200: OpenApiResponse(response=LoopRunPageSerializer, description="Run history page"),
            404: OpenApiResponse(description="Loop not found"),
        },
        summary="List loop runs",
        description="Run history for a loop, newest first, cursor-paginated.",
    )
    @action(detail=True, methods=["get"], url_path="runs", required_scopes=["loop:read"], pagination_class=None)
    def runs(self, request, pk=None, **kwargs):
        query = request.validated_query_data
        page = loops_facade.list_loop_runs(
            pk,
            self.team_id,
            request.user,
            cursor=query.get("cursor"),
            limit=query.get("limit", loops_facade.DEFAULT_LOOP_RUN_PAGE_SIZE),
        )
        if page is None:
            raise NotFound()
        return Response(LoopRunPageSerializer({"results": page.runs, "next_cursor": page.next_cursor}).data)

    @extend_schema(
        summary="Preview a loop fire",
        description=(
            "Dry run: renders the assembled instructions and trigger context for a supplied sample "
            "payload (or a synthetic schedule fire when omitted), without creating a task, run, or "
            "any other side effect."
        ),
        request=LoopPreviewRequestSerializer,
        responses={200: LoopPreviewSerializer, 404: OpenApiResponse(description="Loop not found")},
    )
    @action(detail=True, methods=["post"], url_path="preview", required_scopes=["loop:read"], pagination_class=None)
    def preview(self, request, pk=None, **kwargs):
        serializer = LoopPreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sample_payload = {
            "trigger_type": serializer.validated_data["trigger_type"],
            "payload": serializer.validated_data.get("payload"),
        }
        result = loops_facade.preview_loop(pk, self.team_id, request.user, sample_payload=sample_payload)
        if result is None:
            raise NotFound()
        return Response(LoopPreviewSerializer(result).data)
