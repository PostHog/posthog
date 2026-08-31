from collections.abc import Iterable

from posthog.models import User

from products.subscriptions.backend.models import RepositoryGrant
from products.tasks.backend.facade import api as tasks_api


def repository_grant_authorization_is_live(*, team_id: int, grant: RepositoryGrant) -> bool:
    if grant.authorizer_id != grant.automation_owner_id:
        return False
    if not User.objects.filter(id=grant.automation_owner_id, is_active=True).exists():
        return False
    authorization = tasks_api.resolve_repository_authorization(
        team_id=team_id,
        user_id=grant.automation_owner_id,
        repository=grant.repository,
        github_integration_id=grant.integration_id,
    )
    return (
        authorization is not None
        and authorization.repository.strip().lower() == grant.repository.strip().lower()
        and authorization.github_integration_id == grant.integration_id
        and authorization.github_installation_id == grant.repository_installation_id
    )


def repository_grants_authorizations_are_live(grants: Iterable[RepositoryGrant]) -> dict[object, bool]:
    """Resolve each distinct live repository authorization once for a scheduled batch."""
    grant_list = list(grants)
    active_owner_ids = set(
        User.objects.filter(id__in={grant.automation_owner_id for grant in grant_list}, is_active=True).values_list(
            "id", flat=True
        )
    )
    authorization_by_binding: dict[tuple[int, int, str, int, str], bool] = {}
    result: dict[object, bool] = {}
    for grant in grant_list:
        if (
            grant.authorizer_id != grant.automation_owner_id
            or grant.automation_owner_id not in active_owner_ids
            or not grant.repository_installation_id
        ):
            result[grant.id] = False
            continue
        repository = grant.repository.strip().lower()
        binding = (
            grant.team_id,
            grant.automation_owner_id,
            repository,
            grant.integration_id,
            grant.repository_installation_id,
        )
        if binding not in authorization_by_binding:
            authorization = tasks_api.resolve_repository_authorization(
                team_id=grant.team_id,
                user_id=grant.automation_owner_id,
                repository=grant.repository,
                github_integration_id=grant.integration_id,
            )
            authorization_by_binding[binding] = (
                authorization is not None
                and authorization.repository.strip().lower() == repository
                and authorization.github_integration_id == grant.integration_id
                and authorization.github_installation_id == grant.repository_installation_id
            )
        result[grant.id] = authorization_by_binding[binding]
    return result
