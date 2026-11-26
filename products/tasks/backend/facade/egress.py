from uuid import UUID

from products.tasks.backend.facade.contracts import AgentEgressGitGrantDTO, AgentEgressRegistrationDTO
from products.tasks.backend.logic.services.agent_egress_git import AgentEgressGitGrants, GitGrantUnavailable


def get_git_read_grant(
    *, team_id: int, run_id: UUID, execution_id: UUID, region: str, repository: str
) -> AgentEgressGitGrantDTO | None:
    grant = AgentEgressGitGrants(region=region).lookup(
        team_id=team_id, run_id=run_id, execution_id=execution_id, repository=repository
    )
    if grant is None:
        return None
    registration, credential = grant
    if registration.git_read_grant_version is None:
        raise GitGrantUnavailable("Git grant version is unavailable")
    return AgentEgressGitGrantDTO(
        registration=AgentEgressRegistrationDTO(
            run_id=registration.task_run_id,
            team_id=registration.team_id,
            execution_id=registration.execution_id,
            actor_id=registration.actor_id,
            actor_epoch=registration.actor_epoch,
            relay_key_sha256=registration.relay_key_sha256,
            authority=registration.authority,
            region=registration.region,
            lease_expires_at=registration.lease_expires_at,
            revoked=registration.revoked,
        ),
        repository=credential.repository,
        credential_version=registration.git_read_grant_version,
        expires_at=credential.expires_at,
        token=credential.token.get_secret_value(),
    )
