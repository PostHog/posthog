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
from posthog.models.team.team import Team

from products.signals.backend.facade.api import (
    ScoutRunRejectionKind,
    WorkflowScoutRunRejected,
    start_workflow_scout_run,
)
from products.tasks.backend.facade.workflow_tasks import (
    WorkflowTaskConnectorsInvalid,
    WorkflowTaskLimitExceeded,
    WorkflowTaskOriginKeyConflict,
    WorkflowTaskOwnerIneligible,
    WorkflowTaskRateCapped,
    WorkflowTaskSlackContext,
    WorkflowTaskTeamRateCapped,
    WorkflowTaskUsageLimited,
    create_workflow_task,
)
from products.workflows.backend.models import HogFlow
from products.workflows.backend.service_jwt import TASKS_CREATE_PURPOSE

logger = structlog.get_logger(__name__)

# How a refused scout run reaches the step. The step only treats 409 as a graceful skip, so every
# backpressure kind (paused, in flight, cooldown, budget, quota) maps onto it; a scout that cannot
# run at all fails the step so the author notices.
_SCOUT_REJECTION_STATUS: dict[ScoutRunRejectionKind, int] = {
    ScoutRunRejectionKind.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ScoutRunRejectionKind.FORBIDDEN: status.HTTP_403_FORBIDDEN,
    ScoutRunRejectionKind.CONFLICT: status.HTTP_409_CONFLICT,
    ScoutRunRejectionKind.THROTTLED: status.HTTP_409_CONFLICT,
}


class WorkflowTasksJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = TASKS_CREATE_PURPOSE

    # nosemgrep: tuple-return-prefer-dataclass -- DRF's (user, auth) authentication contract
    def _authenticate_claims(self, request: Request, claims: dict[str, Any]) -> tuple[Any, Any]:
        user, _ = super()._authenticate_claims(request, claims)
        # The workflow is identified by the verified token, never by the request body, so a
        # token minted for one workflow can't create tasks attributed to another.
        try:
            hog_flow_id = uuid.UUID(str(claims.get("hog_flow_id")))
        except ValueError:
            raise AuthenticationFailed("Service token is missing its workflow claim.")
        return user, hog_flow_id


class WorkflowTaskSlackContextSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(
        help_text="PostHog Slack integration that received the triggering message."
    )
    channel = serializers.CharField(max_length=64, help_text="Slack channel ID of the triggering message.")
    thread_ts = serializers.CharField(max_length=64, help_text="Slack thread timestamp the task replies under.")
    message_ts = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        help_text="Timestamp of the triggering message itself. Differs from thread_ts when a reply started the run.",
    )
    slack_user_id = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        help_text="Slack user who posted the triggering message. Empty when a bot posted it.",
    )
    slack_team_id = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        help_text="Slack workspace ID, the fallback for resolving the integration when the stamped ID is stale.",
    )
    is_ext_shared_channel = serializers.BooleanField(
        required=False,
        help_text="Whether the channel is shared with another Slack workspace. Such a channel needs an approval on file before the task replies in it.",
    )


class WorkflowTaskCreateSerializer(serializers.Serializer):
    scout = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        help_text=(
            "Name of a scout in this project. When set, the step runs that scout instead of creating a "
            "task, and the task fields are ignored."
        ),
    )
    prompt = serializers.CharField(
        required=False, allow_blank=True, help_text="Instructions for the agent. Required unless a scout is named."
    )
    event = serializers.DictField(
        required=False,
        help_text="The event that triggered the workflow run. Rendered into the agent's prompt as data.",
    )
    slack_context = WorkflowTaskSlackContextSerializer(
        required=False,
        help_text="Slack thread that triggered the workflow. The task posts its updates there.",
    )
    title = serializers.CharField(
        max_length=255, required=False, allow_blank=True, help_text="Task title. Derived from the prompt when omitted."
    )
    repository = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="GitHub repository as organization/repo. Omit for a task with no code access.",
    )
    model = serializers.CharField(
        max_length=128, required=False, allow_blank=True, help_text="Model ID from the task model catalogue."
    )
    reasoning_effort = serializers.CharField(
        max_length=32, required=False, allow_blank=True, help_text="Reasoning effort the chosen model supports."
    )
    connectors = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        help_text="MCP server installation IDs the run may mount. Must be active team-shared installations or personal ones of the workflow owner.",
    )
    posthog_mcp_scopes = serializers.ChoiceField(
        choices=["read_only", "full"],
        default="read_only",
        help_text="What the PostHog MCP inside the sandbox may do.",
    )
    max_parallel_tasks = serializers.IntegerField(
        min_value=1,
        max_value=100,
        default=5,
        help_text="Reject the create while this workflow already has this many runs in flight.",
    )
    idempotency_key = serializers.CharField(
        max_length=128,
        required=False,
        help_text="Stable key for this invocation. A retried request with the same key returns the existing task.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not (attrs.get("scout") or "").strip() and not (attrs.get("prompt") or "").strip():
            raise serializers.ValidationError({"prompt": "Instructions are required unless a scout is named."})
        return attrs


class WorkflowTaskResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Task ID.")
    run_id = serializers.UUIDField(allow_null=True, help_text="Run started for the task.")


class WorkflowScoutRunResponseSerializer(serializers.Serializer):
    scout = serializers.CharField(help_text="The scout that was run.")
    workflow_id = serializers.CharField(help_text="Temporal workflow ID of the dispatched scout run.")


class WorkflowTaskRejectedSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the task was not created.")


class WorkflowTaskViewSet(viewsets.GenericViewSet):
    """Create AI tasks from a workflow's "Create AI task" action. Authenticated by a scoped
    service JWT minted by the plugin server, never by a user credential.

    A request that names a scout starts a run of that scout instead of creating a task. The run
    is a pure kick: nothing from the triggering event reaches it, so the scout explores exactly as
    it does on its schedule. The scout path has no idempotency replay of its own; a retried step
    that overlaps the run it started collides with it and is answered with a 409, which the step
    records as a skip."""

    authentication_classes = [WorkflowTasksJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowTaskCreateSerializer

    @extend_schema(
        request=WorkflowTaskCreateSerializer,
        responses={
            201: WorkflowTaskResponseSerializer,
            200: OpenApiResponse(
                response=WorkflowTaskResponseSerializer,
                description="The idempotency key was already used; this is the task it created",
            ),
            202: OpenApiResponse(
                response=WorkflowScoutRunResponseSerializer,
                description="A scout was named and its run was dispatched. It runs asynchronously; poll the scout's runs for the result",
            ),
            403: OpenApiResponse(
                response=WorkflowTaskRejectedSerializer,
                description="A scout was named but the workflow lives in a child environment, which cannot run scouts",
            ),
            404: OpenApiResponse(
                response=WorkflowTaskRejectedSerializer,
                description="A scout was named but no runnable scout of that name exists in this project",
            ),
            409: OpenApiResponse(
                response=WorkflowTaskRejectedSerializer,
                description=(
                    "The task was not created: the workflow is at its in-flight or daily limit, "
                    "the project is at its daily limit of workflow-created tasks, "
                    "the owner is over the AI usage limit, or the idempotency key belongs to another workflow. "
                    "Or a scout was named and it is paused, already running, or over its cooldown, budget, or quota"
                ),
            ),
            422: OpenApiResponse(
                response=WorkflowTaskRejectedSerializer,
                description="The workflow no longer exists or has no usable owner",
            ),
        },
        summary="Create an AI task from a workflow",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        # Both from the verified token, not the URL or body.
        user = cast(InternalAPIUser, request.user)
        team_id = cast(int, user.current_team_id)
        hog_flow_id = cast(uuid.UUID, request.auth)

        serializer = WorkflowTaskCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        scout = (data.get("scout") or "").strip()
        if scout:
            return _run_scout(team_id=team_id, hog_flow_id=hog_flow_id, skill_name=scout)

        owner_id = _resolve_workflow_owner(team_id, hog_flow_id)
        if owner_id is None:
            return _rejected("Workflow has no owner who can run tasks.", status.HTTP_422_UNPROCESSABLE_ENTITY)

        try:
            result = create_workflow_task(
                team=Team.objects.get(id=team_id),
                hog_flow_id=hog_flow_id,
                owner_id=owner_id,
                prompt=(data.get("prompt") or "").strip(),
                title=data.get("title"),
                repository=data.get("repository") or None,
                model=data.get("model") or None,
                reasoning_effort=data.get("reasoning_effort") or None,
                mcp_installation_ids=data.get("connectors"),
                posthog_mcp_scopes=data["posthog_mcp_scopes"],
                max_parallel_tasks=data["max_parallel_tasks"],
                origin_key=data.get("idempotency_key"),
                event=data.get("event"),
                slack_context=(
                    WorkflowTaskSlackContext(**data["slack_context"]) if data.get("slack_context") else None
                ),
            )
        except WorkflowTaskConnectorsInvalid as error:
            raise serializers.ValidationError(
                {"connectors": f"MCP installation(s) not found or inactive: {error.invalid_ids}"}
            )
        except WorkflowTaskOwnerIneligible:
            return _rejected("Workflow has no owner who can run tasks.", status.HTTP_422_UNPROCESSABLE_ENTITY)
        except WorkflowTaskOriginKeyConflict:
            return _rejected("Idempotency key is already used by another workflow.", status.HTTP_409_CONFLICT)
        except WorkflowTaskLimitExceeded as error:
            logger.info(
                "workflow_task_create_throttled",
                team_id=team_id,
                hog_flow_id=str(hog_flow_id),
                in_flight=error.in_flight,
            )
            return _rejected(
                f"Workflow already has {error.in_flight} tasks in flight (limit {error.limit}).",
                status.HTTP_409_CONFLICT,
            )
        except WorkflowTaskRateCapped as error:
            logger.info(
                "workflow_task_create_rate_capped",
                team_id=team_id,
                hog_flow_id=str(hog_flow_id),
                cap=error.cap,
            )
            return _rejected(
                f"This workflow reached its daily limit of {error.cap} tasks. "
                "The event was skipped. Task creation resumes automatically within 24 hours.",
                status.HTTP_409_CONFLICT,
            )
        except WorkflowTaskTeamRateCapped as error:
            logger.info(
                "workflow_task_create_team_rate_capped",
                team_id=team_id,
                hog_flow_id=str(hog_flow_id),
                cap=error.cap,
            )
            return _rejected(
                f"This project reached its daily limit of {error.cap} tasks created by workflows. "
                "The event was skipped. Task creation resumes automatically within 24 hours.",
                status.HTTP_409_CONFLICT,
            )
        except WorkflowTaskUsageLimited:
            logger.info(
                "workflow_task_create_usage_limited",
                team_id=team_id,
                hog_flow_id=str(hog_flow_id),
            )
            return _rejected(
                "The workflow owner is over the AI usage limit, so no task was created. "
                "Task creation resumes when the limit resets.",
                status.HTTP_409_CONFLICT,
            )

        return Response(
            WorkflowTaskResponseSerializer({"id": result.task_id, "run_id": result.run_id}).data,
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


def _run_scout(*, team_id: int, hog_flow_id: uuid.UUID, skill_name: str) -> Response:
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
        return _rejected(error.rejection.detail, _SCOUT_REJECTION_STATUS[error.rejection.kind])

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
    return Response(WorkflowTaskRejectedSerializer({"detail": detail}).data, status=http_status)


def _resolve_workflow_owner(team_id: int, hog_flow_id: uuid.UUID) -> int | None:
    """The workflow's creator, who the run executes as. Read from the row rather than the
    request so a token can never assert a different user. Eligibility (active account,
    current project access) is enforced in-transaction by the tasks service."""
    hog_flow = HogFlow.objects.filter(team_id=team_id, id=hog_flow_id).only("created_by_id").first()
    if hog_flow is None or hog_flow.created_by_id is None:
        return None
    return hog_flow.created_by_id
