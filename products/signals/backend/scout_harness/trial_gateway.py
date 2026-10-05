from posthog.llm.gateway_client import GatewayNotConfiguredError, ensure_scout_trial_capture_ready
from posthog.models import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.models import SignalScoutRun
from products.tasks.backend.facade.api import mint_private_gateway_token, revoke_private_gateway_token


def create_trial_gateway_token(run: SignalScoutRun) -> str:
    from products.signals.backend.facade.api import (  # noqa: PLC0415 -- the facade imports report tools
        is_scout_trial_task_run,
    )

    ensure_scout_trial_capture_ready()
    current = SignalScoutRun.objects.for_team(run.team_id).select_related("task_run__task__team").get(id=run.id)
    task_run = current.task_run
    task = task_run.task
    if (
        task.team_id != run.team_id
        or task_run.team_id != run.team_id
        or not is_scout_trial_task_run(team_id=run.team_id, task_id=task.id, task_run_id=task_run.id)
    ):
        raise GatewayNotConfiguredError("Report safety requires a validated scout trial")
    actor = User.objects.filter(
        id=task.created_by_id, is_active=True, organization_membership__organization_id=task.team.organization_id
    ).first()
    if actor is None or not UserAccessControl(user=actor, team=task.team).has_project_access:
        raise GatewayNotConfiguredError("The scout trial operator no longer has access to this project")
    return mint_private_gateway_token(team_id=run.team_id, user=actor.distinct_id, expires_in_seconds=600)


def revoke_trial_gateway_token(token: str) -> None:
    revoke_private_gateway_token(token)
