"""Facade for other products to run a workflow on demand.

Workflows isn't a CI-isolated product yet, but this is the single, stable entry point callers
(e.g. conversations quick actions) should use to run a HogFlow, rather than reaching into the
model or the plugin-server HTTP helpers directly.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from posthog.plugins.plugin_server_api import create_hog_flow_manual_invocation

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


class HogFlowNotRunnableError(Exception):
    """Raised when a workflow can't be run on demand (missing, wrong team, or not active)."""


def workflow_is_runnable(team_id: int, workflow_id: str | UUID) -> bool:
    """True if an active workflow with this id exists for the team."""
    return HogFlow.objects.filter(team_id=team_id, id=workflow_id, status=HogFlow.State.ACTIVE).exists()


def invoke_hog_flow_now(team_id: int, workflow_id: str | UUID, globals: dict[str, Any]) -> None:
    """Run an active workflow's full graph against a caller-synthesized event context.

    `globals` is `{event: {...}, person?: {...}, groups?: {...}}`. Raises HogFlowNotRunnableError
    if the workflow isn't an active flow for the team, or if the plugin-server rejects the run.
    """
    if not workflow_is_runnable(team_id, workflow_id):
        raise HogFlowNotRunnableError("That workflow does not exist or is not active.")

    response = create_hog_flow_manual_invocation(team_id, str(workflow_id), {"globals": globals})
    if not response.ok:
        raise HogFlowNotRunnableError(f"Workflow run was rejected ({response.status_code}).")
