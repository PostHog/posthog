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

from products.signals.backend.facade.api import (
    ScoutRunRejectionKind,
    WorkflowScoutRunRejected,
    start_workflow_scout_run,
)
from products.workflows.backend.models import HogFlow
from products.workflows.backend.service_jwt import SIGNALS_SCOUT_RUN_PURPOSE

logger = structlog.get_logger(__name__)

# How a Signals rejection is surfaced. 409 and 429 are declared non-failure statuses on the
# template, so the workflow step reads them as a graceful skip; everything else fails the step,
# which is what a node pointing at a scout that cannot run should do.
_REJECTION_STATUS: dict[ScoutRunRejectionKind, int] = {
    ScoutRunRejectionKind.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ScoutRunRejectionKind.FORBIDDEN: status.HTTP_403_FORBIDDEN,
    ScoutRunRejectionKind.CONFLICT: status.HTTP_409_CONFLICT,
    ScoutRunRejectionKind.THROTTLED: status.HTTP_429_TOO_MANY_REQUESTS,
}


class WorkflowScoutRunJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = SIGNALS_SCOUT_RUN_PURPOSE

    # nosemgrep: tuple-return-prefer-dataclass -- DRF's (user, auth) authentication contract
    def _authenticate_claims(self, request: Request, claims: dict[str, Any]) -> tuple[Any, Any]:
        user, _ = super()._authenticate_claims(request, claims)
        # The workflow is identified by the verified token, never by the request body, so a token
        # minted for one workflow can't start runs attributed to another.
        try:
            hog_flow_id = uuid.UUID(str(claims.get("hog_flow_id")))
        except ValueError:
            raise AuthenticationFailed("Service token is missing its workflow claim.")
        return user, hog_flow_id


class WorkflowScoutRunCreateSerializer(serializers.Serializer):
    skill_name = serializers.CharField(
        max_length=200, help_text="Name of the scout to run, as shown in the project's scout fleet."
    )
    idempotency_key = serializers.CharField(
        max_length=128,
        required=False,
        help_text=(
            "Stable key for this workflow step. Logged for tracing only — the run is single-flighted "
            "per (project, scout), so a retry cannot produce a second run."
        ),
    )


class WorkflowScoutRunResponseSerializer(serializers.Serializer):
    skill_name = serializers.CharField(help_text="The scout that was run.")
    workflow_id = serializers.CharField(help_text="Temporal workflow id of the dispatched run.")
    started = serializers.BooleanField(help_text="Always true; a rejected fire is a 4xx instead.")


class WorkflowScoutRunRejectedSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the run was not started.")


class WorkflowScoutRunViewSet(viewsets.GenericViewSet):
    """Start Signals scout runs from a workflow's "Run scout" action. Authenticated by a scoped
    service JWT minted by the plugin server, never by a user credential.

    The run is a pure kick: nothing from the triggering event is forwarded, so the scout explores
    exactly as it would on its schedule."""

    authentication_classes = [WorkflowScoutRunJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowScoutRunCreateSerializer

    @extend_schema(
        request=WorkflowScoutRunCreateSerializer,
        responses={
            202: OpenApiResponse(
                response=WorkflowScoutRunResponseSerializer,
                description="A run was dispatched. It executes asynchronously; poll the scout's runs for the result.",
            ),
            403: OpenApiResponse(
                response=WorkflowScoutRunRejectedSerializer,
                description="Signals scouts are not enabled for this project",
            ),
            404: OpenApiResponse(
                response=WorkflowScoutRunRejectedSerializer,
                description="No runnable scout of that name exists in this project",
            ),
            409: OpenApiResponse(
                response=WorkflowScoutRunRejectedSerializer,
                description="A run for this scout is already in flight, or the scout is paused",
            ),
            422: OpenApiResponse(
                response=WorkflowScoutRunRejectedSerializer,
                description="The workflow no longer exists",
            ),
            429: OpenApiResponse(
                response=WorkflowScoutRunRejectedSerializer,
                description="The workflow cooldown, the daily run budget, the Signals credits quota, or the daily report limit binds",
            ),
        },
        summary="Run a Signals scout from a workflow",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        # Both from the verified token, not the URL or body.
        user = cast(InternalAPIUser, request.user)
        team_id = cast(int, user.current_team_id)
        hog_flow_id = cast(uuid.UUID, request.auth)

        serializer = WorkflowScoutRunCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        skill_name = serializer.validated_data["skill_name"].strip()
        # Correlates the log lines below with one workflow step across the fetch retry chain, which
        # re-sends the identical request. Deliberately not a dedupe key: the run is single-flighted
        # per (project, scout), so a retry cannot start a second one.
        step_key = serializer.validated_data.get("idempotency_key")

        # A token outlives the workflow it was minted for (its TTL covers the whole fetch retry
        # chain), so a deleted workflow must not still be able to spend runs.
        if not HogFlow.objects.filter(team_id=team_id, id=hog_flow_id).exists():
            return _rejected("Workflow no longer exists.", status.HTTP_422_UNPROCESSABLE_ENTITY)

        try:
            started = start_workflow_scout_run(team_id=team_id, skill_name=skill_name)
        except WorkflowScoutRunRejected as error:
            rejection = error.rejection
            logger.info(
                "workflow_scout_run_rejected",
                team_id=team_id,
                hog_flow_id=str(hog_flow_id),
                skill_name=skill_name,
                reason=rejection.reason,
                step_key=step_key,
            )
            return _rejected(rejection.detail, _REJECTION_STATUS[rejection.kind])

        logger.info(
            "workflow_scout_run_started",
            team_id=team_id,
            hog_flow_id=str(hog_flow_id),
            skill_name=started.skill_name,
            workflow_id=started.workflow_id,
            step_key=step_key,
        )
        return Response(
            WorkflowScoutRunResponseSerializer(
                {"skill_name": started.skill_name, "workflow_id": started.workflow_id, "started": True}
            ).data,
            status=status.HTTP_202_ACCEPTED,
        )


def _rejected(detail: str, http_status: int) -> Response:
    return Response(WorkflowScoutRunRejectedSerializer({"detail": detail}).data, status=http_status)
