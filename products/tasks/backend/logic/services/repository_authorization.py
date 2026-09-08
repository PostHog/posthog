"""Fail-closed GitHub repository authority for staged Task workflows."""

from __future__ import annotations

import re
import json
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from urllib.parse import quote
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet

from posthog.models.github_integration_base import INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration

from products.tasks.backend.facade.repository_authorization import (
    AuthorizableRepository,
    ResolvedStagedRepositoryBinding,
)
from products.tasks.backend.logic.services.run_actor import user_has_current_team_access

_REPOSITORY_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_BRANCH_NAME = re.compile(r"^[A-Za-z0-9._/-]+$")
_COMMIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


@dataclass(frozen=True)
class _RepositoryAuthorization:
    repository: str
    github_integration_id: int
    github_user_integration_id: UUID
    github_installation_id: str
    team_cache_updated_at: datetime | None
    personal_cache_updated_at: datetime | None


def list_authorizable_repositories(*, team_id: int, actor_id: int) -> tuple[AuthorizableRepository, ...]:
    """Return only repositories writable through both current actor and team grants."""
    if not _actor_has_current_team_access(team_id=team_id, actor_id=actor_id):
        return ()
    return tuple(
        AuthorizableRepository(
            repository=authorization.repository,
            github_integration_id=authorization.github_integration_id,
            github_user_integration_id=authorization.github_user_integration_id,
            github_installation_id=authorization.github_installation_id,
        )
        for authorization in _authorizations(team_id=team_id, actor_id=actor_id)
    )


def resolve_staged_repository_binding(
    *, team_id: int, actor_id: int, repository: str, github_integration_id: int | None = None
) -> ResolvedStagedRepositoryBinding | None:
    """Resolve an exact authorization and the current default branch reference.

    The GitHub request deliberately uses the team's installation transport. Personal OAuth
    credentials only attest that the actor has matching write authority and never leave this
    service or its credential store.
    """
    normalized_repository = _normalize_repository(repository)
    if normalized_repository is None or not _actor_has_current_team_access(team_id=team_id, actor_id=actor_id):
        return None

    candidates = [
        authorization
        for authorization in _authorizations(team_id=team_id, actor_id=actor_id)
        if _normalize_repository(authorization.repository) == normalized_repository
        and (github_integration_id is None or authorization.github_integration_id == github_integration_id)
    ]
    if len(candidates) != 1:
        return None
    candidate = candidates[0]

    # Do not hold database locks over the network call. We revalidate the exact quiet rows
    # before and after it, so a revocation in either direction fails closed.
    authorized = _revalidate_authorization(team_id=team_id, actor_id=actor_id, candidate=candidate)
    if authorized is None:
        return None
    base = _resolve_current_base(
        team_id=team_id,
        github_integration_id=authorized.github_integration_id,
        github_installation_id=candidate.github_installation_id,
        repository=authorized.repository,
    )
    if base is None:
        return None
    base_branch, base_sha = base

    authorized = _revalidate_authorization(team_id=team_id, actor_id=actor_id, candidate=candidate)
    if authorized is None or authorized.repository != candidate.repository:
        return None
    return ResolvedStagedRepositoryBinding(
        repository=authorized.repository,
        base_sha=base_sha,
        base_branch=base_branch,
        github_integration_id=authorized.github_integration_id,
        github_user_integration_id=authorized.github_user_integration_id,
        github_installation_id=authorized.github_installation_id,
        grant_version=_grant_version(authorized, base_branch=base_branch, base_sha=base_sha),
    )


def _actor_has_current_team_access(*, team_id: int, actor_id: int) -> bool:
    team = Team.objects.filter(id=team_id).first()
    actor = User.objects.filter(id=actor_id).first()
    return team is not None and actor is not None and user_has_current_team_access(actor, team)


def _authorizations(*, team_id: int, actor_id: int) -> list[_RepositoryAuthorization]:
    authorizations: list[_RepositoryAuthorization] = []
    personal_integrations = _usable_personal_integrations(_personal_integration_queryset(actor_id))
    for team_integration in _active_team_integrations(team_id):
        installation_id = _installation_id(team_integration)
        if installation_id is None:
            continue
        team_repositories = _writable_repositories(team_integration.repository_cache)
        for personal_integration in personal_integrations:
            if _installation_id(personal_integration) != installation_id:
                continue
            for normalized_repository, personal_repository in _writable_repositories(
                personal_integration.repository_cache
            ).items():
                team_repository = team_repositories.get(normalized_repository)
                if team_repository is None or _normalize_repository(personal_repository) != normalized_repository:
                    continue
                authorizations.append(
                    _RepositoryAuthorization(
                        repository=team_repository,
                        github_integration_id=team_integration.id,
                        github_user_integration_id=personal_integration.id,
                        github_installation_id=installation_id,
                        team_cache_updated_at=team_integration.repository_cache_updated_at,
                        personal_cache_updated_at=personal_integration.repository_cache_updated_at,
                    )
                )
    return sorted(
        authorizations,
        key=lambda authorization: (
            authorization.repository.casefold(),
            authorization.github_integration_id,
            str(authorization.github_user_integration_id),
        ),
    )


def _revalidate_authorization(
    *, team_id: int, actor_id: int, candidate: _RepositoryAuthorization
) -> _RepositoryAuthorization | None:
    if not _actor_has_current_team_access(team_id=team_id, actor_id=actor_id):
        return None
    normalized_repository = _normalize_repository(candidate.repository)
    if normalized_repository is None:
        return None
    with transaction.atomic():
        team_integration = (
            _active_team_integrations(team_id)
            .select_for_update(of=("self",))
            .filter(id=candidate.github_integration_id)
            .first()
        )
        personal_integration = (
            _personal_integration_queryset(actor_id)
            .select_for_update(of=("self",))
            .filter(id=candidate.github_user_integration_id)
            .first()
        )
        if team_integration is None or personal_integration is None:
            return None
        installation_id = _installation_id(team_integration)
        if (
            installation_id is None
            or installation_id != candidate.github_installation_id
            or installation_id != _installation_id(personal_integration)
        ):
            return None
        if not _personal_integration_is_usable(personal_integration):
            return None
        team_repository = _writable_repositories(team_integration.repository_cache).get(normalized_repository)
        personal_repository = _writable_repositories(personal_integration.repository_cache).get(normalized_repository)
        if team_repository is None or personal_repository is None:
            return None
        return _RepositoryAuthorization(
            repository=team_repository,
            github_integration_id=team_integration.id,
            github_user_integration_id=personal_integration.id,
            github_installation_id=installation_id,
            team_cache_updated_at=team_integration.repository_cache_updated_at,
            personal_cache_updated_at=personal_integration.repository_cache_updated_at,
        )


def _resolve_current_base(
    *, team_id: int, github_integration_id: int, github_installation_id: str, repository: str
) -> tuple[str, str] | None:
    integration = _active_team_integrations(team_id).filter(id=github_integration_id).first()
    if integration is None or _installation_id(integration) != github_installation_id:
        return None
    try:
        github = GitHubIntegration(integration)
        repository_data = github._gh_api_get(f"/repos/{repository}", endpoint="/repos/{owner}/{repo}")
        if not _live_repository_is_authorized(repository_data, repository):
            return None
        base_branch = repository_data.get("default_branch")
        if not isinstance(base_branch, str) or not _is_safe_branch(base_branch):
            return None
        branch_data = github._gh_api_get(
            f"/repos/{repository}/branches/{quote(base_branch, safe='')}",
            endpoint="/repos/{owner}/{repo}/branches/{branch}",
        )
    except Exception:
        return None
    commit = branch_data.get("commit")
    base_sha = commit.get("sha") if isinstance(commit, dict) else None
    if not isinstance(base_sha, str) or not _COMMIT_SHA.fullmatch(base_sha):
        return None
    return base_branch, base_sha.lower()


def _live_repository_is_authorized(repository_data: dict[object, object], repository: str) -> bool:
    normalized_repository = _normalize_repository(repository)
    full_name = repository_data.get("full_name")
    return (
        normalized_repository is not None
        and isinstance(full_name, str)
        and full_name == repository
        and _repository_is_permitted(repository_data, normalized_repository)
    )


def _active_team_integrations(team_id: int) -> QuerySet[Integration]:
    return Integration.objects.filter(team_id=team_id, kind=Integration.IntegrationKind.GITHUB, errors="").exclude(
        config__has_key=INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY
    )


def _personal_integration_queryset(actor_id: int) -> QuerySet[UserIntegration]:
    return UserIntegration.objects.filter(
        user_id=actor_id,
        kind=UserIntegration.IntegrationKind.GITHUB,
    ).exclude(config__has_key=INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY)


def _usable_personal_integrations(integrations: Iterable[UserIntegration]) -> list[UserIntegration]:
    return [integration for integration in integrations if _personal_integration_is_usable(integration)]


def _personal_integration_is_usable(integration: UserIntegration) -> bool:
    github = UserGitHubIntegration(integration)
    return (
        not github.user_access_token_expired()
        and not github.user_refresh_token_expired()
        and bool(github.user_refresh_token)
        and bool(github.user_access_token)
    )


def _installation_id(integration: Integration | UserIntegration) -> str | None:
    return (
        integration.integration_id
        if isinstance(integration.integration_id, str) and integration.integration_id
        else None
    )


def _writable_repositories(repository_cache: object) -> dict[str, str]:
    if not isinstance(repository_cache, list):
        return {}
    writable: dict[str, str] = {}
    for repository in repository_cache:
        if not isinstance(repository, dict) or repository.get("can_push") is not True:
            continue
        repository_values = cast(dict[object, object], repository)
        full_name = repository_values.get("full_name")
        normalized = _normalize_repository(full_name)
        if (
            normalized is not None
            and isinstance(full_name, str)
            and _repository_is_permitted(repository_values, normalized)
        ):
            writable.setdefault(normalized, full_name)
    return writable


def _repository_is_permitted(repository: dict[object, object], normalized_repository: str) -> bool:
    visibility = _repository_visibility(repository)
    return visibility == "private" or (
        visibility == "public" and normalized_repository in _public_repository_allowlist()
    )


def _repository_visibility(repository: dict[object, object]) -> str | None:
    private = repository.get("private")
    visibility = repository.get("visibility")
    if private is not None and type(private) is not bool:
        return None
    if visibility is not None and not isinstance(visibility, str):
        return None
    if visibility not in {None, "private", "public"}:
        return None
    if private is True:
        return "private" if visibility in {None, "private"} else None
    if private is False:
        return "public" if visibility in {None, "public"} else None
    return visibility


def _public_repository_allowlist() -> set[str]:
    configured = getattr(settings, "PULSE_PUBLIC_REPOSITORY_ALLOWLIST", ())
    if not isinstance(configured, (list, tuple, set, frozenset)):
        return set()
    return {normalized for value in configured if (normalized := _normalize_repository(value)) is not None}


def _normalize_repository(value: object) -> str | None:
    if not isinstance(value, str) or value != value.strip():
        return None
    owner, separator, repository = value.partition("/")
    if (
        not separator
        or "/" in repository
        or not _REPOSITORY_SEGMENT.fullmatch(owner)
        or not _REPOSITORY_SEGMENT.fullmatch(repository)
        or owner in {".", ".."}
        or repository in {".", ".."}
    ):
        return None
    return value.casefold()


def _is_safe_branch(branch: str) -> bool:
    return (
        bool(_BRANCH_NAME.fullmatch(branch))
        and ".." not in branch
        and not branch.startswith("/")
        and not branch.endswith("/")
    )


def _grant_version(authorization: _RepositoryAuthorization, *, base_branch: str, base_sha: str) -> str:
    payload = {
        "repository": authorization.repository,
        "base_branch": base_branch,
        "base_sha": base_sha,
        "github_integration_id": authorization.github_integration_id,
        "github_user_integration_id": str(authorization.github_user_integration_id),
        "github_installation_id": authorization.github_installation_id,
        "team_cache_updated_at": _cache_version(authorization.team_cache_updated_at),
        "personal_cache_updated_at": _cache_version(authorization.personal_cache_updated_at),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _cache_version(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
