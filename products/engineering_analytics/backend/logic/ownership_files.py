"""The credential for reading a repository's ownership files.

The credential comes only from the source the read is scoped to. Another source of the team can
list the same repository, and its credential would hand the caller data that the per-source
warehouse RBAC denies them. A read with no usable source credential falls back to the team's GitHub
integration, and then to the anonymous public reader.
"""

from posthog.egress.limiter.policies import Priority
from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models.integration import GitHubIntegration
from posthog.models.team import Team
from posthog.ownership.github_files import EGRESS_SOURCE, AuthenticatedRepoFiles, GitHubFilesFetcher, fetcher_for_team

from products.warehouse_sources.backend.facade import api as warehouse_sources
from products.warehouse_sources.backend.facade.contracts import GitHubSourceCredential

from .ownership import ProbeableRepoFiles


def _fetcher_for_credential(
    team_id: int, credential: GitHubSourceCredential, *, priority: Priority
) -> GitHubFilesFetcher | None:
    if credential.personal_access_token:
        return GitHubFilesFetcher.from_token(credential.personal_access_token, priority=priority)
    if credential.integration_id is None:
        return None
    try:
        integration = IntegrationManager.github.oauth.get(team_id, credential.integration_id)
    except IntegrationNotFound:
        return None
    github = GitHubIntegration(integration, source=EGRESS_SOURCE, priority=priority)
    return GitHubFilesFetcher.from_integration(github, priority=priority)


def repo_files(team: Team, repository: str, *, source_id: str, priority: Priority) -> ProbeableRepoFiles:
    """``source_id`` must be the source the caller resolved this repository from. Pass an empty
    string for a read that has no selected source."""
    credential = warehouse_sources.github_source_credential(team_id=team.pk, source_id=source_id) if source_id else None
    if credential is not None:
        fetcher = _fetcher_for_credential(team.pk, credential, priority=priority)
        if fetcher is not None:
            return AuthenticatedRepoFiles(repository, fetcher)
    return fetcher_for_team(team.pk, repository, priority=priority)
