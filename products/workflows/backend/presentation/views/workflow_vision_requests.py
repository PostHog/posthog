import uuid
from typing import Any, cast

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser, ScopedServiceJWTAuthentication

from products.replay_vision.backend.facade.api import start_workflow_observation_request
from products.replay_vision.backend.facade.contracts import (
    MAX_SESSION_ID_LENGTH,
    ObservationRequestRejected,
    RejectionKind,
)
from products.workflows.backend.facade.api import WorkflowNotFound, get_workflow_owner_id
from products.workflows.backend.facade.service_jwt import WORKFLOW_VISION_REQUEST_PURPOSE

logger = structlog.get_logger(__name__)

# A misconfigured step fails loudly on any of these; none is backpressure the step should skip on.
_REJECTION_STATUS: dict[RejectionKind, int] = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "consent": status.HTTP_400_BAD_REQUEST,
    "invalid": status.HTTP_400_BAD_REQUEST,
    "forbidden": status.HTTP_403_FORBIDDEN,
}

MAX_WORKFLOW_SESSIONS = 200


class WorkflowVisionRequestsJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = WORKFLOW_VISION_REQUEST_PURPOSE

    # nosemgrep: tuple-return-prefer-dataclass -- DRF's (user, auth) authentication contract
    def _authenticate_claims(self, request: Request, claims: dict[str, Any]) -> tuple[Any, Any]:
        user, _ = super()._authenticate_claims(request, claims)
        # The workflow comes from the verified token, never the body, so one workflow's token can't act for another.
        try:
            hog_flow_id = uuid.UUID(str(claims.get("hog_flow_id")))
        except ValueError:
            raise AuthenticationFailed("Service token is missing its workflow claim.")
        return user, hog_flow_id


class WorkflowVisionRequestCreateSerializer(serializers.Serializer):
    session_ids = serializers.ListField(
        child=serializers.CharField(max_length=MAX_SESSION_ID_LENGTH),
        allow_empty=False,
        max_length=MAX_WORKFLOW_SESSIONS,
        help_text=f"Session recording IDs to scan, at most {MAX_WORKFLOW_SESSIONS}.",
    )
    scanner_id = serializers.UUIDField(
        required=False, allow_null=True, help_text="A saved scanner to scan with. Pass this or `prompt`."
    )
    prompt = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=4000,
        help_text="What to look for in the sessions, in plain language. Pass this or `scanner_id`.",
    )
    wait_for_session_end = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Hold the scan until the session has been quiet for 35 minutes, so it is scanned whole.",
    )
    idempotency_key = serializers.CharField(
        max_length=200,
        help_text="Stable key for this step visit. A retried request with the same key returns the first request.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if bool(attrs.get("scanner_id")) == bool((attrs.get("prompt") or "").strip()):
            raise serializers.ValidationError("Pass either `scanner_id` or `prompt`.")
        return attrs


class WorkflowVisionSessionResultSerializer(serializers.Serializer):
    session_id = serializers.CharField(help_text="The session recording this answer is for.")
    state = serializers.CharField(help_text="Where the session ended up, for example 'succeeded' or 'skipped'.")
    output = serializers.JSONField(
        allow_null=True, help_text="The scanner's answer. Null unless the session succeeded."
    )


class WorkflowVisionRequestResponseSerializer(serializers.Serializer):
    request_id = serializers.UUIDField(help_text="The Replay vision scan request this step started.")
    status = serializers.ChoiceField(
        choices=[("running", "Running"), ("completed", "Completed")],
        help_text="'completed' when every session already settled, so there is nothing to wait for.",
    )
    sessions = WorkflowVisionSessionResultSerializer(
        many=True,
        required=False,
        help_text="Set only when `status` is 'completed': the same per-session answers a parked step is woken with.",
    )
    session_count = serializers.IntegerField(required=False, help_text="Sessions in the request. Set when completed.")
    succeeded_count = serializers.IntegerField(required=False, help_text="Sessions with an answer. Set when completed.")
    failed_count = serializers.IntegerField(required=False, help_text="Sessions whose scan failed. Set when completed.")
    ineligible_count = serializers.IntegerField(
        required=False, help_text="Sessions the scanner can't analyze, such as too short. Set when completed."
    )
    skipped_count = serializers.IntegerField(
        required=False, help_text="Sessions not scanned because a limit was reached. Set when completed."
    )
    lost_count = serializers.IntegerField(
        required=False, help_text="Sessions that never settled before the scan timed out. Set when completed."
    )


class WorkflowVisionRequestRejectedSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the scan was not started.")


class WorkflowVisionRequestViewSet(viewsets.GenericViewSet):
    """Start a Replay vision scan for the workflow's "Analyze sessions with Replay vision" action.

    Authenticated by a scoped service JWT the plugin server mints, never by a user credential, with its
    own signing key and audience. The step parks until the scan finishes and wakes with the answers."""

    authentication_classes = [WorkflowVisionRequestsJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowVisionRequestCreateSerializer

    @extend_schema(
        request=WorkflowVisionRequestCreateSerializer,
        responses={
            200: OpenApiResponse(
                response=WorkflowVisionRequestResponseSerializer,
                description="This idempotency key already started a request. Nothing new was started.",
            ),
            202: OpenApiResponse(
                response=WorkflowVisionRequestResponseSerializer,
                description="The scan request started. The step wakes when every session has settled.",
            ),
            400: OpenApiResponse(
                response=WorkflowVisionRequestRejectedSerializer,
                description="AI analysis is off for the organization, or the question is invalid",
            ),
            403: OpenApiResponse(
                response=WorkflowVisionRequestRejectedSerializer,
                description="The workflow's owner can't view recordings or can't use this scanner",
            ),
            404: OpenApiResponse(
                response=WorkflowVisionRequestRejectedSerializer,
                description="The scanner doesn't exist in this project",
            ),
            422: OpenApiResponse(
                response=WorkflowVisionRequestRejectedSerializer, description="The workflow no longer exists"
            ),
        },
        summary="Start a Replay vision scan from a workflow",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        # Both come from the verified token, not the URL or body.
        user = cast(InternalAPIUser, request.user)
        team_id = cast(int, user.current_team_id)
        hog_flow_id = cast(uuid.UUID, request.auth)

        serializer = WorkflowVisionRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            owner_id = get_workflow_owner_id(team_id=team_id, workflow_id=hog_flow_id)
        except WorkflowNotFound:
            return _rejected("Workflow no longer exists.", status.HTTP_422_UNPROCESSABLE_ENTITY)

        try:
            started = start_workflow_observation_request(
                team_id=team_id,
                owner_id=owner_id,
                session_ids=data["session_ids"],
                scanner_id=data.get("scanner_id"),
                prompt=data.get("prompt"),
                idempotency_key=data["idempotency_key"],
                wait_for_session_end=data["wait_for_session_end"],
            )
        except ObservationRequestRejected as error:
            logger.info(
                "workflow_vision_request_rejected", team_id=team_id, hog_flow_id=str(hog_flow_id), kind=error.kind
            )
            return _rejected(error.detail, _REJECTION_STATUS[error.kind])

        logger.info(
            "workflow_vision_request_started",
            team_id=team_id,
            hog_flow_id=str(hog_flow_id),
            request_id=str(started.request_id),
            created=started.created,
        )
        # A settled request returns the body a parked step is woken with, so the step output has one shape either way.
        body = {**(started.result or {}), "request_id": started.request_id, "status": started.status}
        return Response(
            WorkflowVisionRequestResponseSerializer(body).data,
            status=status.HTTP_202_ACCEPTED if started.created else status.HTTP_200_OK,
        )


def _rejected(detail: str, http_status: int) -> Response:
    return Response(WorkflowVisionRequestRejectedSerializer({"detail": detail}).data, status=http_status)
