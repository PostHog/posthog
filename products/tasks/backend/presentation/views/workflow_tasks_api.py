from typing import Any

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import ScopedServiceJWTAuthentication
from posthog.models.integration import Integration
from posthog.models.team.team import Team

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.temporal import execute_task_processing_workflow
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.service_jwt import TASKS_CREATE_PURPOSE

logger = structlog.get_logger(__name__)

ACTIVE_RUN_STATUSES = [TaskRun.Status.NOT_STARTED, TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS]

DEFAULT_MAX_PARALLEL_TASKS = 5


class TasksCreateJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = TASKS_CREATE_PURPOSE


class SlackOriginContextSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["slack"], help_text="Discriminator for the context shape.")
    channel = serializers.CharField(max_length=64, help_text="Slack channel ID the task should reply in.")
    thread_ts = serializers.CharField(max_length=64, help_text="Slack thread timestamp to reply under.")
    slack_user_id = serializers.CharField(
        max_length=64, required=False, allow_blank=True, help_text="Slack ID of whoever triggered the workflow."
    )
    slack_team_id = serializers.CharField(
        max_length=64, required=False, allow_blank=True, help_text="Slack workspace ID the message came from."
    )


class WorkflowTaskCreateSerializer(serializers.Serializer):
    hog_flow_id = serializers.UUIDField(help_text="Workflow whose action is creating this task.")
    prompt = serializers.CharField(help_text="Instructions for the agent.")
    title = serializers.CharField(
        max_length=255, required=False, allow_blank=True, help_text="Task title. Derived from the prompt when omitted."
    )
    repository = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="GitHub repository as organization/repo. Omit for a task with no code access.",
    )
    context = SlackOriginContextSerializer(
        required=False, help_text="Where the task should report back. Only Slack is supported today."
    )
    model = serializers.CharField(
        max_length=128, required=False, allow_blank=True, help_text="Model id from the task model catalogue."
    )
    reasoning_effort = serializers.CharField(
        max_length=32, required=False, allow_blank=True, help_text="Reasoning effort the chosen model supports."
    )
    connectors = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        help_text="MCP server installation IDs the run may mount.",
    )
    max_parallel_tasks = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        help_text=f"Reject the create while this workflow already has this many runs in flight. Defaults to {DEFAULT_MAX_PARALLEL_TASKS}.",
    )


class WorkflowTaskResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Created task ID.")
    title = serializers.CharField(help_text="Resolved task title.")


class WorkflowTaskRejectedSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the task was not created.")


class WorkflowTaskViewSet(viewsets.GenericViewSet):
    """Create tasks from a workflow's create-task action. Authenticated by a scoped service JWT
    minted by the plugin server, never by a user credential."""

    authentication_classes = [TasksCreateJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowTaskCreateSerializer

    @extend_schema(
        request=WorkflowTaskCreateSerializer,
        responses={
            201: WorkflowTaskResponseSerializer,
            409: OpenApiResponse(
                response=WorkflowTaskRejectedSerializer,
                description="The workflow already has its maximum runs in flight",
            ),
            422: OpenApiResponse(
                response=WorkflowTaskRejectedSerializer,
                description="The workflow no longer exists or has no usable owner",
            ),
        },
        summary="Create a task from a workflow",
        extensions={"x-product": "tasks"},
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        # From the verified token, not the URL.
        team_id = request.user.current_team_id
        serializer = WorkflowTaskCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        hog_flow_id = data["hog_flow_id"]
        owner_id = _resolve_workflow_owner(team_id, hog_flow_id)
        if owner_id is None:
            return Response(
                {"detail": "Workflow has no owner who can run tasks."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        limit = data.get("max_parallel_tasks", DEFAULT_MAX_PARALLEL_TASKS)
        in_flight = TaskRun.objects.filter(
            task__team_id=team_id, task__hog_flow_id=hog_flow_id, status__in=ACTIVE_RUN_STATUSES
        ).count()
        if in_flight >= limit:
            logger.info(
                "workflow_task_create_throttled", team_id=team_id, hog_flow_id=str(hog_flow_id), in_flight=in_flight
            )
            return Response(
                {"detail": f"Workflow already has {in_flight} tasks in flight (limit {limit})."},
                status=status.HTTP_409_CONFLICT,
            )

        prompt = data["prompt"].strip()
        context = data.get("context") or {}

        # start_workflow=False so the Slack thread is bound before the agent can report into it.
        created = tasks_facade.create_and_run_task(
            team=Team.objects.get(id=team_id),
            title=(data.get("title") or "").strip() or prompt[:255],
            description=prompt,
            origin_product=Task.OriginProduct.WORKFLOW,
            user_id=owner_id,
            repository=data.get("repository") or None,
            start_workflow=False,
            **_agent_config(data),
        )

        Task.objects.filter(id=created.task_id).update(hog_flow_id=hog_flow_id, origin_context=context)

        task_run = created.latest_run
        if task_run is None:
            return Response({"detail": "Task was created without a run."}, status=status.HTTP_202_ACCEPTED)

        if context.get("type") == "slack":
            _bind_slack_thread(team_id, created.task_id, task_run.id, context)

        execute_task_processing_workflow(
            task_id=str(created.task_id),
            run_id=str(task_run.id),
            team_id=team_id,
            user_id=owner_id,
            posthog_mcp_scopes="full",
        )
        return Response({"id": created.task_id, "run_id": task_run.id}, status=status.HTTP_201_CREATED)


def _agent_config(data: dict[str, Any]) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if data.get("model"):
        config["model"] = data["model"]
    if data.get("reasoning_effort"):
        config["reasoning_effort"] = data["reasoning_effort"]
    # TODO: validate against what a run can actually mount, the way facade.loops does for loops.
    if data.get("connectors"):
        config["mcp_gateway_server_ids"] = data["connectors"]
    return config


def _bind_slack_thread(team_id: int, task_id: Any, task_run_id: Any, context: dict[str, Any]) -> None:
    """Bind the run to the thread that triggered it so its updates land there. Never raises: a task
    that can't report back is still worth running."""
    from products.slack_app.backend.models import SlackThreadTaskMapping  # noqa: PLC0415

    try:
        integration = Integration.objects.filter(
            team_id=team_id, kind="slack", integration_id=context.get("slack_team_id") or None
        ).first()
        if integration is None:
            integration = Integration.objects.filter(team_id=team_id, kind="slack").first()
        if integration is None:
            logger.warning("workflow_task_slack_bind_no_integration", team_id=team_id)
            return

        SlackThreadTaskMapping.objects.update_or_create(
            integration=integration,
            channel=context["channel"],
            thread_ts=context["thread_ts"],
            defaults={
                "team_id": team_id,
                "slack_workspace_id": integration.integration_id or "",
                "task_id": task_id,
                "task_run_id": task_run_id,
                "mentioning_slack_user_id": context.get("slack_user_id") or "",
                "last_forwarded_ts": context["thread_ts"],
            },
        )
    except Exception:
        logger.exception("workflow_task_slack_bind_failed", team_id=team_id, task_id=str(task_id))


def _resolve_workflow_owner(team_id: int, hog_flow_id: Any) -> int | None:
    """The workflow's creator, who the run authenticates as. Read from the row rather than the
    request so a token can never assert a different user."""
    from products.workflows.backend.models.hog_flow.hog_flow import HogFlow  # noqa: PLC0415

    hog_flow = HogFlow.objects.filter(team_id=team_id, id=hog_flow_id).only("created_by_id").first()
    if hog_flow is None or hog_flow.created_by_id is None:
        return None

    from posthog.models.user import User  # noqa: PLC0415

    if not User.objects.filter(id=hog_flow.created_by_id, is_active=True).exists():
        return None
    return hog_flow.created_by_id
