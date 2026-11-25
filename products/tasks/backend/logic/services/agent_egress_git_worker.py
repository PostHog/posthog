import logging
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction

from pydantic import ValidationError

from products.tasks.backend.logic.services.agent_egress_git import (
    AgentEgressGitGrants,
    GitGrantInvalidCredential,
    GitGrantUnavailable,
    GitReadCredential,
)
from products.tasks.backend.logic.services.run_actor import loop_owner_eligible_for_credentials
from products.tasks.backend.models import AgentEgressRegistration, TaskRun

if TYPE_CHECKING:
    from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import (
        TaskProcessingContext,
    )

logger = logging.getLogger(__name__)


def _repository(run: TaskRun) -> str | None:
    state = run.state or {}
    if state.get("github_read_access") is not True or run.task.repository_integration_id is not None:
        return None
    if state.get("loop_id") is not None and not loop_owner_eligible_for_credentials(
        run.task.created_by_id, run.task.team
    ):
        return None
    repositories = state.get("repositories", [run.task.repository] if run.task.repository else [])
    if not isinstance(repositories, list) or len(repositories) != 1 or not isinstance(repositories[0], str):
        return None
    try:
        return GitReadCredential.validate_repository(repositories[0].lower())
    except ValueError:
        return None


def _clear_grant(grants: AgentEgressGitGrants, registration: AgentEgressRegistration) -> None:
    if registration.git_read_grant_version is not None:
        grants.clear(
            team_id=registration.team_id,
            run_id=registration.task_run_id,
            execution_id=registration.execution_id,
            version=registration.git_read_grant_version,
        )


def _refresh_enabled(registration: AgentEgressRegistration, run: TaskRun) -> bool:
    if registration.git_read_grant_version is not None:
        return (
            AgentEgressRegistration.objects.for_team(registration.team_id)
            .filter(id=registration.id, git_read_grant__isnull=False)
            .exists()
        )
    execution = (run.state or {}).get("agent_egress_probe")
    return (
        isinstance(execution, dict)
        and execution.get("execution_id") == str(registration.execution_id)
        and execution.get("publish_git_read_grant") is True
    )


def publish_agent_egress_git_grant(
    *, team_id: int, run_id: UUID, execution_id: UUID, sandbox_id: str, initialize: bool = False
) -> bool:
    from products.tasks.backend.temporal.process_task.utils import (
        mint_readonly_github_credential,
        resolve_readonly_github_integration,
    )

    grants = AgentEgressGitGrants(region=settings.AGENT_EGRESS_REGION)
    registration = grants.registry.lookup(team_id=team_id, run_id=run_id, execution_id=execution_id)
    if registration is None or registration.sandbox_id != sandbox_id:
        return False
    previous_version = registration.git_read_grant_version
    run = TaskRun.objects.select_related("task__team").get(id=run_id, team_id=team_id)
    if (initialize and previous_version is not None) or (not initialize and not _refresh_enabled(registration, run)):
        return False

    with transaction.atomic():
        repository = _repository(run)
    integration = resolve_readonly_github_integration(team_id) if repository else None
    if integration is None or repository is None:
        _clear_grant(grants, registration)
        return False
    try:
        credential = mint_readonly_github_credential(integration, repository)
    except Exception:
        raise GitGrantUnavailable("Git credential mint unavailable") from None
    if credential is None:
        _clear_grant(grants, registration)
        return False

    with transaction.atomic():
        run = (
            TaskRun.objects.select_for_update(of=("self",)).select_related("task__team").get(id=run_id, team_id=team_id)
        )
        current_integration = resolve_readonly_github_integration(team_id)
        if (
            _repository(run) != repository
            or current_integration is None
            or current_integration.integration.id != integration.integration.id
            or current_integration.github_installation_id != integration.github_installation_id
        ):
            _clear_grant(grants, registration)
            return False
        try:
            grants.publish(
                team_id=team_id,
                run_id=run_id,
                execution_id=execution_id,
                credential=GitReadCredential(
                    repository=repository, token=credential.token, expires_at=credential.expires_at
                ),
                version=uuid4(),
                previous_version=previous_version,
            )
        except (GitGrantInvalidCredential, ValidationError):
            raise GitGrantUnavailable("Git credential publication unavailable") from None
    return True


def refresh_agent_egress_git_grant(ctx: "TaskProcessingContext", *, sandbox_id: str) -> None:
    execution = (ctx.state or {}).get("agent_egress_probe")
    if not isinstance(execution, dict) or not execution.get("execution_id"):
        return
    try:
        publish_agent_egress_git_grant(
            team_id=ctx.team_id,
            run_id=UUID(ctx.run_id),
            execution_id=UUID(execution["execution_id"]),
            sandbox_id=sandbox_id,
        )
    except Exception as error:
        logger.warning(
            "agent_egress_git_refresh_failed",
            extra={"team_id": ctx.team_id, "run_id": ctx.run_id, "error_type": type(error).__name__},
        )
