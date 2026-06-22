from typing import Optional

from posthog.models import Integration
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration

from products.tasks.backend.models import Task


class TeamIntegrationResolver:
    """Resolve the GitHub integration ids to use for a task's PR lookups.

    Order: the task's own configured integration, else the team's default GitHub integration,
    else the task creator's personal GitHub integration. Both the ``output.pr_url`` harvest
    (``load_pr_urls``) and branch discovery (``discover_branch_prs``) need this, so it lives in
    one place to stay in sync. Lookups are cached per team/creator for the life of one activity.
    """

    def __init__(self, team_id: int) -> None:
        self._team_github_id: Optional[int] = (
            Integration.objects.filter(team_id=team_id, kind="github").values_list("id", flat=True).first()
        )
        self._user_github_by_creator: dict[int, Optional[str]] = {}

    def _creator_user_github(self, creator_id: Optional[int]) -> Optional[str]:
        if creator_id is None:
            return None
        if creator_id not in self._user_github_by_creator:
            uid = UserIntegration.objects.filter(user_id=creator_id, kind="github").values_list("id", flat=True).first()
            self._user_github_by_creator[creator_id] = str(uid) if uid else None
        return self._user_github_by_creator[creator_id]

    def resolve(self, task: Task) -> tuple[Optional[int], Optional[str]]:
        team_int = task.github_integration_id
        user_int = str(task.github_user_integration_id) if task.github_user_integration_id else None
        if team_int is None and user_int is None:
            team_int = self._team_github_id
            if team_int is None:
                user_int = self._creator_user_github(task.created_by_id)
        return team_int, user_int


def resolve_github_integration(
    github_integration_id: Optional[int], github_user_integration_id: Optional[str]
) -> GitHubIntegrationBase | None:
    """Instantiate the GitHub integration for the given ids, refreshing an expired token.

    Raises ``ObjectDoesNotExist`` if the id no longer resolves, and may raise on a failed token
    refresh; callers treat both as "skip this PR/branch" rather than aborting the cycle.
    """
    if github_integration_id is not None:
        integration = GitHubIntegration(Integration.objects.get(id=github_integration_id))
        if integration.access_token_expired():
            integration.refresh_access_token()
        return integration
    if github_user_integration_id is not None:
        user_integration = UserGitHubIntegration(UserIntegration.objects.get(id=github_user_integration_id))
        if user_integration.access_token_expired():
            user_integration.refresh_access_token()
        return user_integration
    return None
