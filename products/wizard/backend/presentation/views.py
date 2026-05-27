"""
DRF views for wizard.

Validates JSON via serializers, routes everything through the facade,
returns DTO-shaped responses. No model imports.
"""

from typing import Any

import structlog
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import UpsertWizardSessionInput, UpsertWizardSessionRequest
from products.wizard.backend.presentation.serializers import (
    UpsertWizardSessionRequestSerializer,
    WizardSessionSerializer,
)
from products.wizard.backend.presentation.utils import pagination_window

logger = structlog.get_logger(__name__)


def _log_request_auth(request: Request, *, action: str, team_id: int | None) -> None:
    """Debug-only dump of how the incoming wizard_sessions request authenticated.

    Fires only at DEBUG level — kept around for diagnosing 401/403 chains during
    rollout. Once the wizard CLI auth flow is stable, this can be removed
    entirely.
    """
    if not logger.isEnabledFor(10):  # logging.DEBUG
        return

    authenticator = getattr(request, "successful_authenticator", None)
    auth_type = type(authenticator).__name__ if authenticator else "Anonymous"
    user = getattr(request, "user", None)
    user_id = getattr(user, "id", None) if user and not user.is_anonymous else None

    scopes: list[str] = []
    scoped_teams: list[int] = []
    scoped_organizations: list[str] = []

    pak = getattr(authenticator, "personal_api_key", None)
    if pak is not None:
        scopes = list(pak.scopes or [])
        scoped_teams = list(pak.scoped_teams or [])
        scoped_organizations = list(pak.scoped_organizations or [])

    token = getattr(authenticator, "access_token", None)
    if token is not None:
        scope_str: str = getattr(token, "scope", "") or ""
        scopes = list(scope_str.split())
        scoped_teams = list(getattr(token, "scoped_teams", None) or [])
        scoped_organizations = list(getattr(token, "scoped_organizations", None) or [])

    logger.debug(
        "wizard_sessions request",
        action=action,
        method=request.method,
        path=request.path,
        team_id_from_url=team_id,
        auth_type=auth_type,
        user_id=user_id,
        scopes=scopes,
        scoped_teams=scoped_teams,
        scoped_organizations=scoped_organizations,
    )


class WizardSessionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "wizard_session"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["create"]
    http_method_names = ["get", "post", "head", "options"]
    lookup_field = "session_id"
    lookup_value_regex = r"[^/]+"

    def check_permissions(self, request: Request) -> None:
        """Log the auth state before DRF decides allow/deny. Fires for both 200 and 403."""
        # team_id is a cached_property that can raise on malformed URLs — don't
        # let the diagnostic logger mask a clean 4xx with a 500.
        try:
            team_id = self.team_id
        except (KeyError, ValidationError, NotFound, AttributeError):
            team_id = None
        _log_request_auth(request, action=getattr(self, "action", "<unknown>"), team_id=team_id)
        super().check_permissions(request)

    @extend_schema(
        description=(
            "List wizard sessions for the project, ordered by started_at desc. "
            "This should only be called by the PostHog Wizard. "
            "Optional filters: ?workflow_id=<id> and ?skill_id=<id>."
        ),
        parameters=[
            OpenApiParameter(
                name="workflow_id",
                required=False,
                type=str,
                location=OpenApiParameter.QUERY,
                description="Filter to a single workflow (e.g. 'onboarding').",
            ),
            OpenApiParameter(
                name="skill_id",
                required=False,
                type=str,
                location=OpenApiParameter.QUERY,
                description="Filter to a single skill within the workflow (e.g. 'nextjs').",
            ),
        ],
        responses={200: WizardSessionSerializer(many=True)},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        page_offset, page_limit = pagination_window(request)
        sessions = wizard_facade.list_for_team(
            self.team_id,
            workflow_id=request.query_params.get("workflow_id"),
            skill_id=request.query_params.get("skill_id"),
            offset=page_offset,
            limit=page_limit,
        )
        # `sessions` is already a bounded slice; DRF's paginator can still wrap
        # it so the response shape (count/next/previous) stays consistent.
        page = self.paginate_queryset(sessions)
        if page is not None:
            return self.get_paginated_response(WizardSessionSerializer(page, many=True).data)
        return Response(WizardSessionSerializer(sessions, many=True).data)

    @extend_schema(
        description="Retrieve a single wizard session by its session_id.",
        responses={
            200: WizardSessionSerializer,
            404: OpenApiResponse(description="No session with that id for this project."),
        },
    )
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        session_id = kwargs.get("session_id")
        if not session_id:
            return Response({"detail": "session_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        dto = wizard_facade.get(self.team_id, session_id)
        if dto is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(WizardSessionSerializer(dto).data)

    @extend_schema(
        description=(
            "Upsert a wizard session. The `session_id` key is the idempotency anchor — "
            "reposting the same `session_id` replaces the existing row. Returns 201 on "
            "create, 200 on update."
        ),
        request=UpsertWizardSessionRequestSerializer,
        responses={
            200: WizardSessionSerializer,
            201: WizardSessionSerializer,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = UpsertWizardSessionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        req: UpsertWizardSessionRequest = serializer.save()

        dto, created = wizard_facade.upsert(
            UpsertWizardSessionInput(
                team_id=self.team_id,
                session_id=req.session_id,
                workflow_id=req.workflow_id,
                skill_id=req.skill_id,
                started_at=req.started_at,
                run_phase=req.run_phase,
                tasks=tuple(req.tasks),
                event_plan=req.event_plan,
                error=req.error,
            )
        )
        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(WizardSessionSerializer(dto).data, status=response_status)
