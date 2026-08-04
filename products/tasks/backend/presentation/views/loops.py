import json

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, ProjectSecretAPIKeyAuthentication
from posthog.permissions import APIScopePermission, is_authenticated_via_project_secret_api_key
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
    LoopSkillBundlesWriteSerializer,
    LoopWriteSerializer,
)

MAX_LOOP_TRIGGER_PAYLOAD_BYTES = 64 * 1024
# Whole-request ceiling for the skill_bundles replace, enforced from Content-Length
# before request.data parses. This is the authoritative parse bound for the endpoint:
# DRF parses JSON from the request stream, where Django's DATA_UPLOAD_MAX_MEMORY_SIZE
# is not guaranteed to apply, so the gate must not assume a larger backstop. 20MB fits
# one 10MB decoded bundle plus base64 overhead and dependencies.
MAX_LOOP_SKILL_BUNDLE_REQUEST_BYTES = 20 * 1024 * 1024


def _loop_limit_response(exc: "loops_facade.LoopLimitError") -> Response:
    """Structured 429 for abuse/safety ceilings. `error: "loop_safety_limit"` is the stable
    marker the frontend keys off to tell the user they hit a limit (course-correct or contact
    support) rather than showing a generic failure."""
    return Response(
        {"error": "loop_safety_limit", "code": exc.code, "limit": exc.limit, "detail": exc.detail},
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )


class LoopsPagination(LimitOffsetPagination):
    default_limit = 50
    max_limit = 100

    def get_paginated_response_schema(self, schema):
        # The list runtime augments the page with the per-project loop cap and usage (see
        # LoopViewSet.list); declare them here so the generated OpenAPI/MCP types match. Kept on
        # the paginator, next to the envelope it documents, so drf-spectacular doesn't double-wrap
        # a hand-rolled envelope serializer.
        paginated = super().get_paginated_response_schema(schema)
        paginated["properties"]["max_loops_per_team"] = {
            "type": "integer",
            "description": (
                "Hard cap on non-deleted loops per project. Creating a loop beyond this returns a 429 "
                "with `error: loop_safety_limit`. Authoritative — read this rather than assuming a value."
            ),
        }
        paginated["properties"]["total_loop_count"] = {
            "type": "integer",
            "description": (
                "Current number of non-deleted, user-facing loops in this project, counted against "
                "`max_loops_per_team`. At or above the cap, creation is blocked."
            ),
        }
        return paginated


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

    Exempts PSAK-authenticated service calls (`trigger`, and `runs` readback): a PSAK is a
    project-scoped service credential, not a real user, so the person-targeted `loops` flag
    doesn't apply — the scope (`loop:write`/`loop:read`) and the throttles gate it instead.
    """

    message = "This project does not have access to Loops."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if getattr(view, "action", None) in ("trigger", "runs") and is_authenticated_via_project_secret_api_key(
            request
        ):
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
    # A project secret API key can fire a loop (`trigger`) and read back its run history
    # (`runs`), so a service that triggers can also poll the outcome. Everything else (CRUD,
    # manual run, preview) stays session/PAT/OAuth-only.
    psak_allowed_actions = ["trigger", "runs"]
    # "put" is routed only by the skill_bundles action (wholesale replace); the loop
    # resource itself stays PATCH-only.
    http_method_names = ["get", "post", "patch", "put", "delete", "head", "options"]
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
        description=(
            "List loops visible to the caller: personal loops they own, plus every team loop. The "
            "response also carries `max_loops_per_team` and `total_loop_count` so a client can show "
            "remaining capacity and disable creation at the cap without hardcoding the limit."
        ),
        responses={200: LoopSerializer(many=True)},
    )
    def list(self, request, **kwargs):
        loops = loops_facade.list_loops(self.team_id, request.user)
        page = self.paginate_queryset(loops)
        # Cap + usage travel with the list so the frontend gates creation against the backend's
        # authoritative number (see MAX_LOOPS_PER_TEAM) instead of drifting from its own copy.
        limits = {
            "max_loops_per_team": loops_facade.MAX_LOOPS_PER_TEAM,
            "total_loop_count": loops_facade.count_team_loops(self.team_id),
        }
        if page is not None:
            response = self.get_paginated_response(LoopSerializer(page, many=True).data)
            response.data.update(limits)
            return response
        return Response(
            {
                "count": len(loops),
                "next": None,
                "previous": None,
                "results": LoopSerializer(loops, many=True).data,
                **limits,
            }
        )

    @extend_schema(
        summary="Get a loop", responses={200: LoopSerializer, 404: OpenApiResponse(description="Loop not found")}
    )
    def retrieve(self, request, pk=None, **kwargs):
        loop = loops_facade.get_loop(pk, self.team_id, request.user)
        if loop is None:
            raise NotFound()
        return Response(LoopSerializer(loop).data)

    @extend_schema(
        summary="Create a loop",
        request=LoopWriteSerializer,
        responses={
            201: LoopSerializer,
            429: OpenApiResponse(description="A per-team loop or per-loop trigger safety limit was reached"),
        },
    )
    def create(self, request, **kwargs):
        serializer = self._write_serializer(request.data)
        try:
            loop = loops_facade.create_loop(self.team_id, request.user, dict(serializer.validated_data))
        except loops_facade.LoopLimitError as exc:
            return _loop_limit_response(exc)
        except loops_facade.LoopValidationError as exc:
            raise ValidationError(str(exc))
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
            429: OpenApiResponse(description="A per-loop trigger safety limit was reached"),
        },
    )
    def partial_update(self, request, pk=None, **kwargs):
        serializer = self._write_serializer(request.data, partial=True)
        try:
            loop = loops_facade.update_loop(pk, self.team_id, request.user, dict(serializer.validated_data))
        except loops_facade.LoopLimitError as exc:
            return _loop_limit_response(exc)
        except loops_facade.LoopPermissionError as exc:
            raise PermissionDenied(str(exc))
        except loops_facade.LoopValidationError as exc:
            raise ValidationError(str(exc))
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
        summary="Replace a loop's skill bundles",
        description=(
            "Replaces the loop's attached skill bundles wholesale: zipped local skills whose "
            "contents are seeded into every fired run's sandbox. Send an empty list to detach "
            "every skill. Owner-only on team loops, like other identity-bearing configuration."
        ),
        request=LoopSkillBundlesWriteSerializer,
        responses={
            200: LoopSerializer,
            403: OpenApiResponse(description="Not permitted to change this loop's skills"),
            404: OpenApiResponse(description="Loop not found"),
            411: OpenApiResponse(description="Content-Length header missing"),
            413: OpenApiResponse(description="Request body exceeds the skill bundle size ceiling"),
        },
    )
    @action(detail=True, methods=["put"], url_path="skill_bundles", required_scopes=["loop:write"])
    def skill_bundles(self, request, pk=None, **kwargs):
        # Same shape as `trigger`'s payload gate: require a declared length, then reject
        # oversized requests from it, all before request.data parses (and retains) the
        # body. This gate is the endpoint's authoritative parse bound — see the note on
        # MAX_LOOP_SKILL_BUNDLE_REQUEST_BYTES.
        content_length = _content_length(request)
        if content_length <= 0:
            return Response(
                {"detail": "A Content-Length header is required."},
                status=status.HTTP_411_LENGTH_REQUIRED,
            )
        if content_length > MAX_LOOP_SKILL_BUNDLE_REQUEST_BYTES:
            return Response(
                {"detail": (f"Skill bundle request exceeds {MAX_LOOP_SKILL_BUNDLE_REQUEST_BYTES // (1024 * 1024)}MB.")},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        serializer = LoopSkillBundlesWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            loop = loops_facade.replace_loop_skill_bundles(
                pk, self.team_id, request.user, bundles=list(serializer.validated_data["bundles"])
            )
        except loops_facade.LoopPermissionError as exc:
            raise PermissionDenied(str(exc))
        except loops_facade.LoopValidationError as exc:
            raise ValidationError(str(exc))
        if loop is None:
            raise NotFound()
        return Response(LoopSerializer(loop).data)

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
        # Bound parse work BEFORE touching `request.data`: Django reads at most `Content-Length`
        # bytes for the body, so requiring a declared length within the cap means the JSON parse can
        # never see more than 64 KB. A missing length (chunked transfer) would otherwise let the body
        # stream up to the global upload limit before the size check, so it's rejected here.
        # (`Content-Length`, not `request.body`: permission checks upstream consume the raw stream via
        # `request.POST`, so `request.body` already raises `RawPostDataException` by now.)
        content_length = _content_length(request)
        if content_length <= 0:
            return Response(
                {"detail": "A Content-Length header within 64 KB is required."},
                status=status.HTTP_411_LENGTH_REQUIRED,
            )
        if content_length > MAX_LOOP_TRIGGER_PAYLOAD_BYTES:
            return Response({"detail": "Request body exceeds 64 KB."}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        payload = request.data if isinstance(request.data, dict) else {}
        # Backstop for an understated Content-Length: the parsed body (already bounded to the declared
        # length by Django) must still fit the cap.
        payload_size = len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
        if payload_size > MAX_LOOP_TRIGGER_PAYLOAD_BYTES:
            return Response({"detail": "Request body exceeds 64 KB."}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        if is_authenticated_via_project_secret_api_key(request):
            # A PSAK is a project-wide service credential, so it may fire any of the project's loops.
            result = loops_facade.fire_loop_api(pk, self.team_id, payload, idempotency_key=_idempotency_key(request))
        else:
            # A session/PAT/OAuth caller is a real user: the payload becomes agent prompt content and
            # the run executes as the loop owner, so restrict API triggering to the owner (a member
            # fires a team loop as themselves via `run` instead).
            result = loops_facade.fire_loop_api_for_user(
                pk, self.team_id, request.user, payload, idempotency_key=_idempotency_key(request)
            )
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
        cursor = query.get("cursor")
        limit = query.get("limit", loops_facade.DEFAULT_LOOP_RUN_PAGE_SIZE)
        if is_authenticated_via_project_secret_api_key(request):
            # PSAK is project-wide (it can already trigger any loop), so its readback skips the
            # personal/team visibility split, same as the trigger path.
            page = loops_facade.list_loop_runs_for_service(pk, self.team_id, cursor=cursor, limit=limit)
        else:
            page = loops_facade.list_loop_runs(pk, self.team_id, request.user, cursor=cursor, limit=limit)
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
