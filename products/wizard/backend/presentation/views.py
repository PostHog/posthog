"""
DRF views for wizard.

Validates JSON via serializers, routes everything through the facade,
returns DTO-shaped responses. No model imports.
"""

import time
from collections.abc import AsyncIterator
from typing import Any

from django.conf import settings
from django.http import HttpResponse
from django.http.response import HttpResponseBase

import structlog
import posthoganalytics
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.renderers import BaseRenderer
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.streaming import sse_streaming_response
from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import (
    UpsertWizardSessionInput,
    UpsertWizardSessionRequest,
    WizardSessionDTO,
)
from products.wizard.backend.presentation.serializers import (
    UpsertWizardSessionRequestSerializer,
    WizardSessionSerializer,
)
from products.wizard.backend.presentation.utils import pagination_window

logger = structlog.get_logger(__name__)


class EventStreamRenderer(BaseRenderer):
    """Satisfies DRF content negotiation for `Accept: text/event-stream`; never actually invoked."""

    media_type = "text/event-stream"
    format = "event-stream"
    charset = "utf-8"

    def render(self, data: Any, accepted_media_type: str | None = None, renderer_context: Any = None) -> bytes:
        return data if isinstance(data, bytes) else b""


def _log_request_auth(request: Request, *, action: str, team_id: int | None) -> None:
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


SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0
SSE_POLL_TIMEOUT_SECONDS = 1.0
# Long-lived connections pin NGINX Unit processes during recycle-drain; the
# `event: end` close makes EventSource reconnect, so the cap is near-invisible to
# users (the progress tracker may show a brief "reconnecting" blip per rotation).
SSE_MAX_DURATION_SECONDS = 15 * 60

WIZARD_SYNC_KILLSWITCH_FLAG = "onboarding-wizard-sync-killswitch"


def _wizard_sync_killswitch_enabled(distinct_id: str) -> bool:
    # Local-only eval: no per-request network/decide call on this hot endpoint.
    # Flag definitions are served via HyperCache (posthog/apps.py). Fail-open:
    # if the flag can't be evaluated locally, the stream behaves normally.
    return bool(
        posthoganalytics.feature_enabled(
            WIZARD_SYNC_KILLSWITCH_FLAG,
            distinct_id,
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    )


class WizardSessionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "wizard_session"
    scope_object_read_actions = ["list", "retrieve", "stream", "latest"]
    scope_object_write_actions = ["create"]
    http_method_names = ["get", "post", "head", "options"]
    lookup_field = "session_id"
    # Negative lookahead so a session_id of `stream` or `latest` can't collide
    # with the `@action(url_path=...)` detail-vs-action routes.
    lookup_value_regex = r"(?!(?:stream|latest)$)[^/]+"

    def check_permissions(self, request: Request) -> None:
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
            skill_id=request.query_params.get("skill_id") or None,
            offset=page_offset,
            limit=page_limit,
        )
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

    def _killswitch_active(self, request: Request) -> bool:
        # Shared by `latest` and `stream` so flipping the incident flag quiets both the
        # SSE stream and the 60s REST poll — otherwise the fleet keeps hitting `latest`.
        user = getattr(request, "user", None)
        distinct_id = (
            str(user.distinct_id)
            if user is not None and not user.is_anonymous and getattr(user, "distinct_id", None)
            else f"team:{self.team_id}"
        )
        return _wizard_sync_killswitch_enabled(distinct_id)

    @extend_schema(
        description=(
            "Return the single most-recent wizard session for a workflow (and "
            "optional skill), or 204 if none exists. Unlike `list`, this is a "
            "point lookup the app shell uses to decide whether to open the live "
            "SSE stream — it never returns a collection, and 'no run' is a 204 "
            "rather than a 404 so clients don't conflate it with a missing "
            "endpoint."
        ),
        parameters=[
            OpenApiParameter(
                name="workflow_id",
                required=True,
                type=str,
                location=OpenApiParameter.QUERY,
                description="Filter to a single workflow (e.g. 'posthog-integration').",
            ),
            OpenApiParameter(
                name="skill_id",
                required=False,
                type=str,
                location=OpenApiParameter.QUERY,
                description="Filter to a single skill within the workflow (e.g. 'nextjs').",
            ),
        ],
        responses={
            200: WizardSessionSerializer,
            204: OpenApiResponse(description="No session for this workflow/skill in this project."),
        },
    )
    @action(detail=False, methods=["get"], url_path="latest")
    def latest(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # Killswitch parity with `stream`: a 204 makes the client treat this as "no run"
        # and wind the detector down, so flipping the flag in an incident also stops the
        # 60s poll (and skips the DB read entirely), not just the SSE stream.
        if self._killswitch_active(request):
            return Response(status=status.HTTP_204_NO_CONTENT)
        workflow_id = request.query_params.get("workflow_id")
        if not workflow_id:
            raise ValidationError({"detail": "workflow_id is required."})
        skill_id = request.query_params.get("skill_id") or None
        dto = wizard_facade.get_latest(self.team_id, workflow_id, skill_id)
        if dto is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
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

    @extend_schema(
        description=(
            "Server-Sent Events stream of wizard session updates for a "
            "(workflow_id, skill_id) pair. On connect, the current latest "
            "session (if any) is emitted as the first event; subsequent "
            "upserts are streamed in real time. The server closes the "
            f"connection after {SSE_MAX_DURATION_SECONDS} seconds with an "
            "`event: end` line so the client (EventSource) can reconnect.\n\n"
            "**SDK consumers**: do not call the generated fetch wrapper for "
            "this path — it will buffer the entire infinite stream. Use the "
            "URL builder (`getWizardSessionsStreamRetrieveUrl`) with the "
            "browser's `EventSource` API instead."
        ),
        parameters=[
            OpenApiParameter(
                name="workflow_id",
                required=True,
                type=str,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name="skill_id",
                required=False,
                type=str,
                location=OpenApiParameter.QUERY,
            ),
        ],
        responses={
            (200, "text/event-stream"): {
                "type": "string",
                "description": "SSE stream of WizardSession events.",
            }
        },
    )
    @action(detail=False, methods=["get"], url_path="stream", renderer_classes=[EventStreamRenderer])
    def stream(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponseBase:
        # Killswitch first, before any other work: a 204 tells EventSource to stop
        # reconnecting, severing the self-reconnect loop for already-open tabs.
        if self._killswitch_active(request):
            return HttpResponse(status=204)

        workflow_id = request.query_params.get("workflow_id")
        skill_id = request.query_params.get("skill_id") or None
        if not workflow_id:
            raise ValidationError({"detail": "workflow_id is required."})

        # The generator is `async def` — WSGI can't consume an async iterator.
        if getattr(settings, "SERVER_GATEWAY_INTERFACE", "ASGI") != "ASGI":
            raise RuntimeError("wizard_sessions.stream requires ASGI.")

        generator = _wizard_session_event_stream(
            team_id=self.team_id,
            workflow_id=workflow_id,
            skill_id=skill_id,
            request=request,
        )
        # Releases the request-thread DB connection (auth, team resolution) before
        # the long-lived stream begins — see sse_streaming_response.
        return sse_streaming_response(generator)


async def _wizard_session_event_stream(
    team_id: int,
    workflow_id: str,
    skill_id: str | None,
    request: Request | None = None,
) -> AsyncIterator[bytes]:
    """Stream SSE bytes for a wizard session subscription.

    Subscribes first, then fetches initial state, so publishes that race the
    snapshot are buffered on the pubsub socket and drained on the next tick.
    """
    started_at = time.monotonic()

    async with wizard_facade.subscribe_to_updates(team_id, workflow_id, skill_id) as pubsub:

        def _get_initial() -> WizardSessionDTO | None:
            with team_scope(team_id):
                return wizard_facade.get_latest(team_id, workflow_id, skill_id)

        # database_sync_to_async releases the DB connection after the read so it
        # isn't pinned for the whole SSE stream (CONN_MAX_AGE=0; loop is Redis-only).
        latest = await database_sync_to_async(_get_initial, thread_sensitive=False)()
        if latest is not None:
            yield b"data: " + wizard_facade.serialize_dto(latest) + b"\n\n"

        last_heartbeat = time.monotonic()
        while True:
            if time.monotonic() - started_at >= SSE_MAX_DURATION_SECONDS:
                yield b"event: end\ndata: reconnect\n\n"
                return

            if request is not None:
                is_disconnected = getattr(request, "is_disconnected", None)
                if is_disconnected is not None:
                    try:
                        if await is_disconnected():
                            return
                    except Exception:
                        pass

            message = await pubsub.get_message(timeout=SSE_POLL_TIMEOUT_SECONDS)
            now = time.monotonic()

            # `pmessage` arrives via pattern subscribe; `message` via exact.
            if message and message.get("type") in ("message", "pmessage"):
                yield b"data: " + message["data"] + b"\n\n"
                last_heartbeat = now
                continue

            if now - last_heartbeat >= SSE_HEARTBEAT_INTERVAL_SECONDS:
                yield b": ping\n\n"
                last_heartbeat = now
