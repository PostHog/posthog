import uuid

import structlog
import posthoganalytics
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import WorkflowsTasksAPIAuthentication
from posthog.models import Team, User

from products.tasks.backend.facade import api as tasks_facade
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

logger = structlog.get_logger(__name__)

AGENT_TASK_FEATURE_FLAG = "workflows-agent-task-step"

# Per-team ceiling on concurrently running workflow-originated tasks. Each task is a real cloud
# sandbox with repo credentials, so an event-triggered workflow must not be able to fan out
# unboundedly (one task per matching event).
MAX_ACTIVE_WORKFLOW_TASK_RUNS_PER_TEAM = 10

MAX_PROMPT_LENGTH = 10_000
MAX_TITLE_LENGTH = 255  # Task.title column limit
MAX_REPOSITORY_LENGTH = 200


def _resolve_task_user(team: Team, hog_flow: HogFlow) -> User | None:
    """The human a workflow-started task runs as: the workflow's creator, verified to still be an
    active member of the team's organization. The task mints a PostHog OAuth token for this user,
    so there is deliberately no fallback — running a prompt somebody else authored under a more
    privileged identity (e.g. an org admin) would be silent escalation."""
    if not hog_flow.created_by_id:
        return None
    return User.objects.filter(
        id=hog_flow.created_by_id,
        is_active=True,
        organization_membership__organization_id=team.organization_id,
    ).first()


def _agent_task_step_enabled(team: Team) -> bool:
    """Server-side gate for the agent_task step — the frontend flag only hides the palette entry.
    Fails closed: a flag-service error means no tasks get created."""
    try:
        return bool(
            posthoganalytics.feature_enabled(
                AGENT_TASK_FEATURE_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
            )
        )
    except Exception:
        logger.warning("workflows.agent_task.flag_check_failed_defaulting_off", team_id=team.id, exc_info=True)
        return False


class InternalWorkflowsAgentTaskViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Internal endpoints for the CDP workflows executor's agent_task step: start a PostHog Code task
    and poll its status. Authenticated with the dedicated WORKFLOWS_TASKS_API_SECRET (not the
    fleet-wide INTERNAL_API_SECRET) and not exposed to public ingress."""

    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer
    authentication_classes = [WorkflowsTasksAPIAuthentication]

    def create(self, request: Request, team_id: str) -> Response:
        try:
            team = Team.objects.select_related("organization").get(id=int(team_id))
        except (Team.DoesNotExist, ValueError):
            return Response({"error": "Team not found"}, status=404)

        prompt = request.data.get("prompt")
        distinct_id = request.data.get("distinct_id")
        workflow_id = request.data.get("workflow_id")
        workflow_run_id = request.data.get("workflow_run_id")
        action_id = request.data.get("action_id")
        if not prompt or not distinct_id or not workflow_id or not workflow_run_id or not action_id:
            return Response(
                {"error": "prompt, distinct_id, workflow_id, workflow_run_id and action_id are required"},
                status=400,
            )
        if len(prompt) > MAX_PROMPT_LENGTH:
            return Response({"error": f"prompt exceeds {MAX_PROMPT_LENGTH} characters"}, status=400)

        if not _agent_task_step_enabled(team):
            return Response({"error": "The agent task step is not enabled for this project"}, status=403)

        hog_flow = HogFlow.objects.filter(id=workflow_id, team=team).first()
        if hog_flow is None:
            return Response({"error": "Workflow not found"}, status=404)
        user = _resolve_task_user(team, hog_flow)
        if user is None:
            return Response(
                {"error": "The workflow's creator is no longer an active member of this organization"}, status=400
            )

        # Idempotency: cyclotron re-executes on crash/timeout, so a replayed create must return the
        # run the earlier attempt already started rather than mint a duplicate task (and PR).
        existing = tasks_facade.find_workflow_agent_task_run(team.id, str(workflow_run_id), str(action_id))
        if existing is not None:
            return Response({"task_run_id": str(existing.id), "status": existing.status})

        if tasks_facade.count_active_workflow_task_runs(team.id) >= MAX_ACTIVE_WORKFLOW_TASK_RUNS_PER_TEAM:
            return Response(
                {"error": f"Too many workflow tasks in flight (limit {MAX_ACTIVE_WORKFLOW_TASK_RUNS_PER_TEAM})"},
                status=429,
            )

        title = (request.data.get("title") or "Workflow task")[:MAX_TITLE_LENGTH]
        repository = request.data.get("repository")
        repository = str(repository)[:MAX_REPOSITORY_LENGTH] if repository else None

        try:
            created = tasks_facade.create_and_run_task(
                team=team,
                title=title,
                description=prompt,
                origin_product=tasks_facade.TaskOriginProduct.WORKFLOW,
                user_id=user.id,
                repository=repository,
                create_pr=bool(request.data.get("create_pr", True)),
                internal=True,
                workflow_agent_task={
                    "distinct_id": str(distinct_id),
                    "workflow_id": str(workflow_id),
                    "workflow_run_id": str(workflow_run_id),
                    "action_id": str(action_id),
                },
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        except Exception:
            logger.exception("Error starting workflow agent task", team_id=team_id, workflow_id=workflow_id)
            return Response({"error": "Internal server error"}, status=500)

        if created.latest_run is None:
            return Response({"error": "Task started without producing a run"}, status=500)

        return Response({"task_run_id": str(created.latest_run.id), "status": created.latest_run.status})

    def retrieve(self, request: Request, team_id: str, pk: str) -> Response:
        try:
            team_id_int = int(team_id)
            run_uuid = uuid.UUID(pk)
        except ValueError:
            return Response({"error": "Task run not found"}, status=404)

        run = tasks_facade.get_task_run(run_uuid, team_id=team_id_int)
        # Scope the dedicated secret to workflow-originated runs — it must not read other products' runs.
        if run is None or run.task_origin_product != tasks_facade.TaskOriginProduct.WORKFLOW:
            return Response({"error": "Task run not found"}, status=404)

        return Response({"status": run.status, "output": run.output, "error_message": run.error_message})
