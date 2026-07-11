import structlog
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import WorkflowsTasksAPIAuthentication
from posthog.models import OrganizationMembership, Team, User

from products.tasks.backend.facade import api as tasks_facade
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

logger = structlog.get_logger(__name__)


def _resolve_task_user(team: Team, hog_flow: HogFlow | None) -> User | None:
    """The human a workflow-started task runs as. The task mints a PostHog OAuth token for this
    user, so it must be an active org member. Prefer the workflow's creator; otherwise fall back to
    the org's highest-level active admin so a system-created workflow can still start tasks."""
    if hog_flow and hog_flow.created_by_id:
        creator = User.objects.filter(id=hog_flow.created_by_id, is_active=True).first()
        if creator is not None:
            return creator
    fallback_id = (
        OrganizationMembership.objects.filter(
            organization_id=team.organization_id,
            user__is_active=True,
            level__gte=OrganizationMembership.Level.ADMIN,
        )
        .order_by("-level", "user_id")
        .values_list("user_id", flat=True)
        .first()
    )
    return User.objects.filter(id=fallback_id).first() if fallback_id is not None else None


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
        if not prompt or not distinct_id or not workflow_id:
            return Response({"error": "prompt, distinct_id and workflow_id are required"}, status=400)

        hog_flow = HogFlow.objects.filter(id=workflow_id, team=team).first()
        user = _resolve_task_user(team, hog_flow)
        if user is None:
            return Response({"error": "No eligible user to run the task as"}, status=400)

        try:
            created = tasks_facade.create_and_run_task(
                team=team,
                title=request.data.get("title") or "Workflow task",
                description=prompt,
                origin_product=tasks_facade.TaskOriginProduct.WORKFLOW,
                user_id=user.id,
                repository=request.data.get("repository") or None,
                create_pr=bool(request.data.get("create_pr", True)),
                internal=True,
                workflow_agent_task={
                    "distinct_id": str(distinct_id),
                    "workflow_id": str(workflow_id),
                    "workflow_run_id": request.data.get("workflow_run_id"),
                    "action_id": request.data.get("action_id"),
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
        except ValueError:
            return Response({"error": "Team not found"}, status=404)

        run = tasks_facade.get_task_run(pk, team_id=team_id_int)
        if run is None:
            return Response({"error": "Task run not found"}, status=404)

        return Response({"status": run.status, "output": run.output, "error_message": run.error_message})
