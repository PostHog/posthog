import re
from datetime import timedelta
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from products.tasks.backend.logic.services.agent_egress import AgentEgressRegistry
from products.tasks.backend.models import AgentEgressRegistration, TaskRun


class GitReadCredential(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    repository: str
    token: SecretStr = Field(repr=False, min_length=1, max_length=8192)
    expires_at: AwareDatetime

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        parts = value.split("/")
        if (
            len(parts) != 2
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,38}", parts[0])
            or not re.fullmatch(r"[a-z0-9_.-]{1,100}", parts[1])
            or parts[1] in (".", "..")
            or parts[1].endswith(".git")
        ):
            raise ValueError("Invalid Git repository")
        return value

    @field_validator("token")
    @classmethod
    def validate_token(cls, value: SecretStr) -> SecretStr:
        token = value.get_secret_value()
        if not token.isascii() or any(character.isspace() or ord(character) < 32 for character in token):
            raise ValueError("Invalid Git credential")
        return value


class GitGrantConflict(ValueError):
    pass


class GitGrantInvalidCredential(ValueError):
    pass


class GitGrantUnavailable(RuntimeError):
    pass


class AgentEgressGitGrants:
    def __init__(self, *, region: str) -> None:
        self.registry = AgentEgressRegistry(region=region)

    def publish(
        self,
        *,
        team_id: int,
        run_id: UUID,
        execution_id: UUID,
        credential: GitReadCredential,
        version: UUID,
        previous_version: UUID | None,
    ) -> None:
        with transaction.atomic():
            TaskRun.objects.select_for_update().get(id=run_id, team_id=team_id)
            registration = self.registry.lookup(team_id=team_id, run_id=run_id, execution_id=execution_id)
            if registration is None:
                raise ValueError("Execution registration is not active")
            now = timezone.now()
            if not now < credential.expires_at <= now + timedelta(hours=1):
                raise GitGrantInvalidCredential("Git credential must expire within one hour")
            payload = {
                "repository": credential.repository,
                "token": credential.token.get_secret_value(),
                "expires_at": credential.expires_at.isoformat(),
            }
            if registration.git_read_grant_version == version:
                if registration.git_read_grant != payload:
                    raise GitGrantConflict("Git grant version cannot be reused")
                return
            if registration.git_read_grant_version != previous_version:
                raise GitGrantConflict("Git grant version has changed")
            registration.git_read_grant = payload
            registration.git_read_grant_version = version
            registration.save(update_fields=["git_read_grant", "git_read_grant_version"])

    def lookup(
        self, *, team_id: int, run_id: UUID, execution_id: UUID, repository: str
    ) -> tuple[AgentEgressRegistration, GitReadCredential] | None:
        registration = self.registry.lookup(team_id=team_id, run_id=run_id, execution_id=execution_id)
        if registration is None:
            return None
        stored = (
            AgentEgressRegistration.objects.for_team(team_id)
            .filter(id=registration.id, task_run_id=run_id, revoked=False, lease_expires_at__gt=timezone.now())
            .values_list("git_read_grant_version", "git_read_grant")
            .first()
        )
        if stored is None or stored[1] is None:
            return None
        version, payload = stored
        try:
            credential = GitReadCredential.model_validate(payload)
        except ValidationError:
            raise GitGrantUnavailable("Git grant is unreadable") from None
        if (
            version is None
            or credential.repository != repository
            or credential.expires_at <= timezone.now()
            or registration.lease_expires_at <= timezone.now()
        ):
            return None
        registration.git_read_grant_version = version
        return registration, credential

    def clear(self, *, team_id: int, run_id: UUID, execution_id: UUID, version: UUID) -> bool:
        with transaction.atomic():
            TaskRun.objects.select_for_update().get(id=run_id, team_id=team_id)
            return bool(
                AgentEgressRegistration.objects.for_team(team_id)
                .filter(
                    task_run_id=run_id,
                    execution_id=execution_id,
                    region=self.registry.region,
                    git_read_grant_version=version,
                )
                .update(git_read_grant=None, git_read_grant_version=uuid4())
            )
