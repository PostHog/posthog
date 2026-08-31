"""Fail-closed repository authorization bindings for external automation grants."""

from collections.abc import Iterable
from typing import cast

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet

from posthog.models.github_integration_base import INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY
from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, Integration
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration

from products.tasks.backend.facade import contracts


def list_authorizable_repositories(
    input: contracts.ListAuthorizableRepositoriesInput,
) -> list[contracts.AuthorizableRepositoryDTO]:
    """Return only repositories both the user and the active team installation can write."""
    team_integrations = _active_team_integrations(input.team_id)
    personal_integrations = _usable_personal_integrations(_personal_integration_queryset(input.user_id))
    authorizations: set[tuple[str, int, str]] = set()

    for team_integration in team_integrations:
        installation_id = _installation_id(team_integration)
        if installation_id is None:
            continue
        team_repositories = _writable_repositories(team_integration.repository_cache)
        if not team_repositories:
            continue
        for personal_integration in personal_integrations:
            if _installation_id(personal_integration) != installation_id:
                continue
            for normalized_repository in _writable_repositories(personal_integration.repository_cache):
                canonical_repository = team_repositories.get(normalized_repository)
                if canonical_repository is not None:
                    authorizations.add((canonical_repository, team_integration.id, installation_id))

    return [
        contracts.AuthorizableRepositoryDTO(
            repository=repository,
            github_integration_id=integration_id,
            github_installation_id=installation_id,
        )
        for repository, integration_id, installation_id in sorted(
            authorizations,
            key=lambda authorization: (authorization[0].casefold(), authorization[1]),
        )
    ]


def resolve_repository_authorization(
    input: contracts.ResolveRepositoryAuthorizationInput,
) -> contracts.AuthorizableRepositoryDTO | None:
    """Revalidate one user-selected repository against its exact active team installation."""
    normalized_repository = _normalize_repository(input.repository)
    if normalized_repository is None:
        return None
    candidates = [
        authorization
        for authorization in list_authorizable_repositories(
            contracts.ListAuthorizableRepositoriesInput(team_id=input.team_id, user_id=input.user_id)
        )
        if _normalize_repository(authorization.repository) == normalized_repository
        and (input.github_integration_id is None or authorization.github_integration_id == input.github_integration_id)
    ]
    if len(candidates) != 1:
        return None
    candidate = candidates[0]

    with transaction.atomic():
        team_integration = (
            _active_team_integrations(input.team_id)
            .select_for_update(of=("self",))
            .filter(id=candidate.github_integration_id)
            .first()
        )
        if team_integration is None:
            return None
        installation_id = _installation_id(team_integration)
        if installation_id is None:
            return None

        team_repository = _writable_repositories(team_integration.repository_cache).get(normalized_repository)
        if team_repository is None:
            return None

        personal_integrations = _usable_personal_integrations(
            _personal_integration_queryset(input.user_id).select_for_update(of=("self",))
        )
        for personal_integration in personal_integrations:
            if _installation_id(personal_integration) != installation_id:
                continue
            if normalized_repository in _writable_repositories(personal_integration.repository_cache):
                return contracts.AuthorizableRepositoryDTO(
                    repository=team_repository,
                    github_integration_id=team_integration.id,
                    github_installation_id=installation_id,
                )
    return None


def repository_is_authorizable(repository_cache: object, repository: str) -> bool:
    """Return whether one cached repository remains eligible for a staged grant."""
    normalized_repository = _normalize_repository(repository)
    return normalized_repository is not None and normalized_repository in _writable_repositories(repository_cache)


def _active_team_integrations(team_id: int) -> QuerySet[Integration]:
    return (
        Integration.objects.filter(team_id=team_id, kind=Integration.IntegrationKind.GITHUB)
        .exclude(errors=ERROR_TOKEN_REFRESH_FAILED)
        .exclude(config__has_key=INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY)
    )


def _personal_integration_queryset(user_id: int) -> QuerySet[UserIntegration]:
    return UserIntegration.objects.filter(
        user_id=user_id,
        kind=UserIntegration.IntegrationKind.GITHUB,
    ).exclude(config__has_key=INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY)


def _usable_personal_integrations(integrations: Iterable[UserIntegration]) -> list[UserIntegration]:
    return [integration for integration in integrations if _personal_integration_is_usable(integration)]


def _personal_integration_is_usable(integration: UserIntegration) -> bool:
    github = UserGitHubIntegration(integration)
    return (
        not github.user_refresh_token_expired() and bool(github.user_refresh_token) and bool(github.user_access_token)
    )


def _installation_id(integration: Integration | UserIntegration) -> str | None:
    installation_id = integration.integration_id
    return installation_id if isinstance(installation_id, str) and installation_id else None


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
    if visibility == "private":
        return True
    if visibility != "public":
        return False
    return normalized_repository in _public_repository_allowlist()


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
    if not separator or not owner or not repository or "/" in repository:
        return None
    return value.casefold()
