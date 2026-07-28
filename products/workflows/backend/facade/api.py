"""Facade for other products to run a workflow on demand.

Workflows isn't a CI-isolated product yet, but this is the single, stable entry point callers
(e.g. conversations quick actions) should use to run a HogFlow, rather than reaching into the
model or the plugin-server HTTP helpers directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from posthog.plugins.plugin_server_api import create_hog_flow_manual_invocation
from posthog.rbac.user_access_control import UserAccessControl

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

if TYPE_CHECKING:
    from posthog.models import Team, User


class HogFlowNotRunnableError(Exception):
    """Raised when a workflow can't be run on demand because it's missing, wrong team, or not active.

    This is a caller error (bad `workflow_id`), so callers should surface it as a 4xx.
    """


class HogFlowServiceError(Exception):
    """Raised when the workflow service (CDP) fails or rejects the run at the HTTP layer.

    Distinct from HogFlowNotRunnableError: the workflow itself is valid, but the downstream call
    failed — e.g. the manual-invocation route isn't deployed yet (a 404 `requests` doesn't raise on)
    or a transient 5xx. Callers should surface it as a 502, not a 400 workflow_id error.
    """


def workflow_is_runnable(team_id: int, workflow_id: str | UUID) -> bool:
    """True if an active workflow with this id exists for the team."""
    return HogFlow.objects.filter(team_id=team_id, id=workflow_id, status=HogFlow.State.ACTIVE).exists()


def user_can_run_workflow(user: User, team: Team, workflow_id: str | UUID) -> bool:
    """True if the user has editor access to this workflow (RBAC object-level check).

    Running a workflow executes its configured actions with their stored secrets, so it requires
    the same access as operating the workflow — not just access to the surface triggering it.
    With no explicit access controls on the workflow, every team member passes (editor default).
    """
    hog_flow = HogFlow.objects.filter(team_id=team.id, id=workflow_id).first()
    if hog_flow is None:
        return False
    return UserAccessControl(user=user, team=team).check_access_level_for_object(hog_flow, "editor")


def invoke_hog_flow_now(team_id: int, workflow_id: str | UUID, globals: dict[str, Any]) -> None:
    """Run an active workflow's full graph against a caller-synthesized event context.

    `globals` is `{event: {...}, person?: {...}, groups?: {...}}`. Raises HogFlowNotRunnableError
    if the workflow isn't an active flow for the team, or HogFlowServiceError if the plugin-server
    rejects the run or is unreachable at the HTTP layer.
    """
    if not workflow_is_runnable(team_id, workflow_id):
        raise HogFlowNotRunnableError("That workflow does not exist or is not active.")

    response = create_hog_flow_manual_invocation(team_id, str(workflow_id), {"globals": globals})
    if not response.ok:
        # A completed non-2xx round-trip (404/5xx) doesn't raise from `requests`, but it's still a
        # service-layer failure, not the workflow being invalid — keep the two distinct for callers.
        raise HogFlowServiceError(f"Workflow run was rejected ({response.status_code}).")
