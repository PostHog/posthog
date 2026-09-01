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
from products.workflows.backend.service_jwt import TASKS_CREATE_PURPOSE

logger = structlog.get_logger(__name__)

# The step only treats 409 as a graceful skip, so every backpressure kind (paused, in flight,
# cooldown, budget, quota) maps onto it; a scout that cannot run at all fails the step so the
# author notices.
_REJECTION_STATUS: dict[ScoutRunRejectionKind, int] = {
    ScoutRunRejectionKind.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ScoutRunRejectionKind.FORBIDDEN: status.HTTP_403_FORBIDDEN,
    ScoutRunRejectionKind.CONFLICT: status.HTTP_409_CONFLICT,
    ScoutRunRejectionKind.THROTTLED: status.HTTP_409_CONFLICT,
}


class WorkflowScoutRunsJWTAuthentication(ScopedServiceJWTAuthentication):
    # Same purpose/secret as the "Create AI task" step: both are the workflow engine dispatching
    # a step for a verified (team, workflow), just to a different agent harness behind it.
    purpose = TASKS_CREATE_PURPOSE

    # nosemgrep: tuple-return-prefer-dataclass -- DRF's (user, auth) authentication contract
    def _authenticate_claims(self, request: Request, claims: dict[str, Any]) -> tuple[Any, Any]:
        user, _ = super()._authenticate_claims(request, claims)
        # The workflow is identified by the verified token, never by the request body, so a
        # token minted for one workflow can't spend another workflow's scout runs.
        try:
            hog_flow_id = uuid.UUID(str(claims.get("hog_flow_id")))
        except ValueError:
            raise AuthenticationFailed("Service token is missing its workflow claim.")
        return user, hog_flow_id


class WorkflowScoutRunCreateSerializer(serializers.Serializer):
    skill_name = serializers.CharField(
        max_length=200, help_text="Name of the scout to run, for example signals-scout-error-tracking."
    )
    idempotency_key = serializers.CharField(
        max_length=128,
        required=False,
        help_text=(
            "Stable key for this invocation. Accepted for parity with the task-creation endpoint; "
            "the scout path has no idempotency replay of its own, since a run in flight already "
            "answers a retried request with a 409 the step records as a skip."
        ),
    )


class WorkflowScoutRunResponseSerializer(serializers.Serializer):
    scout = serializers.CharField(help_text="The scout that was run.")
    workflow_id = serializers.CharField(help_text="Temporal workflow ID of the dispatched scout run.")


class WorkflowScoutRunRejectedSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the scout was not run.")


class WorkflowScoutRunViewSet(viewsets.GenericViewSet):
    """Start a Signals scout run from a workflow's "Run scout" action. Authenticated by the same
    scoped service JWT as the "Create AI task" step, minted by the plugin server, never by a user
    credential.

    A run is a pure kick: nothing from the triggering event reaches the scout, so it explores
    exactly as it does on its schedule. It never stamps the scout's last_run_at and never feeds
    its failure-streak breaker — a workflow trigger is additive to the schedule, not a
    substitute for it."""

    authentication_classes = [WorkflowScoutRunsJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowScoutRunCreateSerializer

    @extend_schema(
        request=WorkflowScoutRunCreateSerializer,
        responses={
            202: OpenApiResponse(
                response=WorkflowScoutRunResponseSerializer,
                description="The scout run was dispatched. It runs asynchronously; poll the scout's runs for the result",
            ),
            403: OpenApiResponse(
                response=WorkflowScoutRunRejectedSerializer,
                description="The workflow lives in a child environment, which cannot run scouts",
            ),
            404: OpenApiResponse(
                response=WorkflowScoutRunRejectedSerializer,
                description="No runnable scout of that name exists in this project",
            ),
            409: OpenApiResponse(
                response=WorkflowScoutRunRejectedSerializer,
                description="The scout is paused, already running, or over its cooldown, daily budget, or quota",
            ),
            422: OpenApiResponse(
                response=WorkflowScoutRunRejectedSerializer,
                description="The workflow no longer exists",
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

        # A token outlives the workflow it was minted for (its TTL covers the whole fetch retry
        # chain), so a deleted workflow must not still be able to spend scout runs.
        if not HogFlow.objects.filter(team_id=team_id, id=hog_flow_id).exists():
            return _rejected("Workflow no longer exists.", status.HTTP_422_UNPROCESSABLE_ENTITY)

        try:
            started = start_workflow_scout_run(team_id=team_id, skill_name=skill_name)
        except WorkflowScoutRunRejected as error:
            logger.info(
                "workflow_scout_run_rejected",
                team_id=team_id,
                hog_flow_id=str(hog_flow_id),
                skill_name=skill_name,
                reason=error.rejection.reason,
            )
            return _rejected(error.rejection.detail, _REJECTION_STATUS[error.rejection.kind])

        logger.info(
            "workflow_scout_run_started",
            team_id=team_id,
            hog_flow_id=str(hog_flow_id),
            skill_name=started.skill_name,
            workflow_id=started.workflow_id,
        )
        return Response(
            WorkflowScoutRunResponseSerializer({"scout": started.skill_name, "workflow_id": started.workflow_id}).data,
            status=status.HTTP_202_ACCEPTED,
        )


def _rejected(detail: str, http_status: int) -> Response:
    return Response(WorkflowScoutRunRejectedSerializer({"detail": detail}).data, status=http_status)
