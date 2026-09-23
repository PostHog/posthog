from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from posthog.llm.gateway_client import GatewayNotConfiguredError, ensure_scout_trial_capture_ready
from posthog.models import User
from posthog.models.oauth import OAuthAccessToken
from posthog.temporal.oauth import create_oauth_access_token_for_user, get_signals_app

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.models import SignalScoutRun

TRIAL_GATEWAY_SCOPES = ["llm_gateway:read", "internal_run:read", "scout_experiment_internal:read"]


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
    application = get_signals_app()
    if application is None:
        raise GatewayNotConfiguredError("The Signals OAuth application must be configured for scout trials")
    with transaction.atomic():
        token = create_oauth_access_token_for_user(
            actor,
            run.team_id,
            scopes=TRIAL_GATEWAY_SCOPES,
            include_internal_scopes=False,
            application="signals",
            sandbox_task_id=task.id,
        )
        if not OAuthAccessToken.objects.filter(token=token, application=application, sandbox_task_id=task.id).update(
            expires=timezone.now() + timedelta(minutes=10)
        ):
            raise GatewayNotConfiguredError("The report safety credential was not bound to the Signals application")
    return token


def revoke_trial_gateway_token(token: str) -> None:
    OAuthAccessToken.objects.filter(token=token).delete()
