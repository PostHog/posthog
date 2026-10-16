import uuid
from typing import Any, cast

from django.db import models

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser

from products.replay_vision.backend.facade.api import (
    MAX_SESSION_ID_LENGTH,
    ObservationRequestRejected,
    RejectionKind,
    parse_workflow_scan_setup,
    start_workflow_observation_request,
)
from products.replay_vision.backend.facade.workflow_scan_limits import (
    WORKFLOW_SCAN_RATE_CAP_PER_DAY,
    WORKFLOW_SCAN_TEAM_RATE_CAP_PER_DAY,
)
from products.workflows.backend.facade.api import (
    WorkflowNotFound,
    get_workflow_owner_id,
    get_workflow_vision_scan_daily_limits,
)
from products.workflows.backend.facade.service_jwt import WORKFLOW_VISION_REQUEST_PURPOSE
from products.workflows.backend.presentation.views.workflow_step_auth import WorkflowStepJWTAuthentication

logger = structlog.get_logger(__name__)

# The step skips the event on a 409 and fails on everything else, so only a daily limit maps to it.
_REJECTION_STATUS: dict[RejectionKind, int] = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "consent": status.HTTP_400_BAD_REQUEST,
    "invalid": status.HTTP_400_BAD_REQUEST,
    "forbidden": status.HTTP_403_FORBIDDEN,
    "rate_limited": status.HTTP_409_CONFLICT,
}


class WorkflowVisionRequestsJWTAuthentication(WorkflowStepJWTAuthentication):
    purpose = WORKFLOW_VISION_REQUEST_PURPOSE


class WorkflowVisionRequestCreateSerializer(serializers.Serializer):
    session_id = serializers.CharField(
        max_length=MAX_SESSION_ID_LENGTH, help_text="The session recording to scan, usually the triggering event's."
    )
    setup = serializers.JSONField(
        help_text=(
            "The step's scan setup: `type` is `scanner` with a `scanner_id`, or a scan type (monitor, classifier, "
            "scorer, summarizer) with a `prompt` and the type's `tags` or `scale`."
        ),
    )
    wait_for_session_end = serializers.BooleanField(
        default=True,
        help_text="Wait until the session has been quiet for 35 minutes before scanning, so the whole session is seen.",
    )
    idempotency_key = serializers.CharField(
        max_length=200, help_text="The step's dispatch key. A retry with the same key returns the first request."
    )


class WorkflowVisionRequestStatus(models.TextChoices):
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"


class WorkflowVisionRequestResponseSerializer(serializers.Serializer):
    request_id = serializers.UUIDField(help_text="The Replay Vision scan request this step started.")
    status = serializers.ChoiceField(
        choices=WorkflowVisionRequestStatus.choices,
        help_text="'completed' when the session already settled, so there is nothing to wait for.",
    )
    state = serializers.CharField(
        required=False,
        help_text="Set when completed: how the session's scan ended, such as succeeded, failed or skipped.",
    )
    output = serializers.JSONField(
        required=False, allow_null=True, help_text="Set when completed: the scan's answer, or null without one."
    )
    warnings = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        help_text="Set when completed: why the answer is missing or was cut, or null.",
    )


class WorkflowVisionRequestRejectedSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the scan was not started.")


class WorkflowVisionRequestViewSet(viewsets.GenericViewSet):
    """Start a Replay Vision scan for the workflow's Replay Vision step.

    Authenticated by a scoped service JWT the plugin server mints, never by a user credential, with its
    own signing key and audience. The step parks until the scan finishes and wakes with the answer."""

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
                description="The scan request started. The step wakes when the session has settled.",
            ),
            400: OpenApiResponse(
                response=WorkflowVisionRequestRejectedSerializer,
                description="AI analysis is off for the organization, or the scan is set up wrong",
            ),
            403: OpenApiResponse(
                response=WorkflowVisionRequestRejectedSerializer,
                description="The workflow's owner can't view recordings or can't use this scanner",
            ),
            404: OpenApiResponse(
                response=WorkflowVisionRequestRejectedSerializer,
                description="The scanner doesn't exist in this project",
            ),
            409: OpenApiResponse(
                response=WorkflowVisionRequestRejectedSerializer,
                description="The workflow or the project reached its daily scan limit, so the event is skipped",
            ),
            422: OpenApiResponse(
                response=WorkflowVisionRequestRejectedSerializer, description="The workflow no longer exists"
            ),
        },
        summary="Start a Replay Vision scan from a workflow",
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

        limits = get_workflow_vision_scan_daily_limits(team_id=team_id)
        try:
            scanner_id, inline = parse_workflow_scan_setup(data["setup"])
            started = start_workflow_observation_request(
                team_id=team_id,
                owner_id=owner_id,
                hog_flow_id=hog_flow_id,
                session_id=data["session_id"],
                scanner_id=scanner_id,
                inline=inline,
                idempotency_key=data["idempotency_key"],
                wait_for_session_end=data["wait_for_session_end"],
                per_workflow_daily_cap=WORKFLOW_SCAN_RATE_CAP_PER_DAY
                if limits.per_workflow is None
                else limits.per_workflow,
                per_team_daily_cap=WORKFLOW_SCAN_TEAM_RATE_CAP_PER_DAY if limits.per_team is None else limits.per_team,
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
        body = {**(started.result or {}), "request_id": started.request_id, "status": started.status}
        # Nullable fields would otherwise serialize as null on a running request, which has no answer yet.
        data = {key: value for key, value in WorkflowVisionRequestResponseSerializer(body).data.items() if key in body}
        return Response(
            data,
            status=status.HTTP_202_ACCEPTED if started.created else status.HTTP_200_OK,
        )


def _rejected(detail: str, http_status: int) -> Response:
    return Response(WorkflowVisionRequestRejectedSerializer({"detail": detail}).data, status=http_status)
