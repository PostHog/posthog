"""Fail-closed repository authority for staged, server-mediated automation."""

from __future__ import annotations

from uuid import UUID

from posthog.dataclasses import frozen


@frozen
class AuthorizableRepository:
    """One repository writable through both the actor and a team installation."""

    repository: str
    github_integration_id: int
    github_user_integration_id: UUID
    github_installation_id: str


@frozen
class ResolvedStagedRepositoryBinding:
    """Immutable, credential-free repository authority for one staged workflow."""

    repository: str
    base_sha: str
    base_branch: str
    github_integration_id: int
    github_user_integration_id: UUID
    github_installation_id: str
    grant_version: str


def list_authorizable_repositories(*, team_id: int, actor_id: int) -> tuple[AuthorizableRepository, ...]:
    """List repositories an actor can write through this team's active GitHub installation."""
    from products.tasks.backend.logic.services.repository_authorization import (  # noqa: PLC0415 - keep Django off facade import
        list_authorizable_repositories as _list_authorizable_repositories,
    )

    return _list_authorizable_repositories(team_id=team_id, actor_id=actor_id)


def resolve_staged_repository_binding(
    *, team_id: int, actor_id: int, repository: str, github_integration_id: int | None = None
) -> ResolvedStagedRepositoryBinding | None:
    """Revalidate one selected repository and resolve its current immutable base."""
    from products.tasks.backend.logic.services.repository_authorization import (  # noqa: PLC0415 - keep Django off facade import
        resolve_staged_repository_binding as _resolve_staged_repository_binding,
    )

    return _resolve_staged_repository_binding(
        team_id=team_id,
        actor_id=actor_id,
        repository=repository,
        github_integration_id=github_integration_id,
    )


def revalidate_staged_repository_binding(
    *,
    team_id: int,
    actor_id: int,
    repository: str,
    github_integration_id: int,
    github_user_integration_id: UUID,
    github_installation_id: str,
) -> bool:
    """Confirm the stored actor and installation authority still permits one repository."""
    from products.tasks.backend.logic.services.repository_authorization import (  # noqa: PLC0415 - keep Django off facade import
        revalidate_staged_repository_binding as _revalidate_staged_repository_binding,
    )

    return _revalidate_staged_repository_binding(
        team_id=team_id,
        actor_id=actor_id,
        repository=repository,
        github_integration_id=github_integration_id,
        github_user_integration_id=github_user_integration_id,
        github_installation_id=github_installation_id,
    )


__all__ = [
    "AuthorizableRepository",
    "ResolvedStagedRepositoryBinding",
    "list_authorizable_repositories",
    "revalidate_staged_repository_binding",
    "resolve_staged_repository_binding",
]
