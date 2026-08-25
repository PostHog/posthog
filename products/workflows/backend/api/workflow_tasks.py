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

from products.tasks.backend.facade.workflow_tasks import (
    WorkflowTaskConnectorsInvalid,
    WorkflowTaskLimitExceeded,
    WorkflowTaskOriginKeyConflict,
    WorkflowTaskOwnerIneligible,
    WorkflowTaskSlackContext,
    create_workflow_task,
)
from products.workflows.backend.models import HogFlow
from products.workflows.backend.service_jwt import TASKS_CREATE_PURPOSE

logger = structlog.get_logger(__name__)


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
    prompt = serializers.CharField(help_text="Instructions for the agent.")
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


class WorkflowTaskResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Task ID.")
    run_id = serializers.UUIDField(allow_null=True, help_text="Run started for the task.")


class WorkflowTaskRejectedSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the task was not created.")


class WorkflowTaskViewSet(viewsets.GenericViewSet):
    """Create AI tasks from a workflow's "Create AI task" action. Authenticated by a scoped
    service JWT minted by the plugin server, never by a user credential."""

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
            409: OpenApiResponse(
                response=WorkflowTaskRejectedSerializer,
                description="The workflow already has its maximum runs in flight, or the idempotency key belongs to another workflow",
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

        owner_id = _resolve_workflow_owner(team_id, hog_flow_id)
        if owner_id is None:
            return _rejected("Workflow has no owner who can run tasks.", status.HTTP_422_UNPROCESSABLE_ENTITY)

        try:
            result = create_workflow_task(
                team=Team.objects.get(id=team_id),
                hog_flow_id=hog_flow_id,
                owner_id=owner_id,
                prompt=data["prompt"].strip(),
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

        return Response(
            WorkflowTaskResponseSerializer({"id": result.task_id, "run_id": result.run_id}).data,
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
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
