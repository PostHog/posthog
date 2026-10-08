"""Where the credential for reading a repository's ownership files comes from.

Engineering analytics reports on a repository the team already connected as a warehouse source, so
that source holds a credential for it. Using it is what lets a private repository resolve at all.
The credential comes from the one source the read is already scoped to, never from a walk over the
team's other sources: a source the caller may not access can list the same repository, and reading
with its credential would hand the caller data the per-source warehouse RBAC denies them. A read
that has no selected source, or whose source holds no usable credential, falls back to the team's
GitHub integration, and then to the anonymous public reader.
"""

from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.team import Team
from posthog.ownership.github_files import EGRESS_SOURCE, AuthenticatedRepoFiles, GitHubFilesFetcher, fetcher_for_team

from products.warehouse_sources.backend.facade import api as warehouse_sources
from products.warehouse_sources.backend.facade.contracts import GitHubSourceCredential

from .ownership import ProbeableRepoFiles


def _fetcher_for_credential(
    team_id: int, credential: GitHubSourceCredential, *, priority: Priority
) -> GitHubFilesFetcher | None:
    if credential.personal_access_token:
        # The token is the customer's own, on the customer's own GitHub budget, so it names no
        # installation for the egress limiter to gate on.
        return GitHubFilesFetcher.from_token(credential.personal_access_token, priority=priority)
    if credential.integration_id is None:
        return None
    integration = Integration.objects.filter(team_id=team_id, id=credential.integration_id, kind="github").first()
    if integration is None:
        return None
    github = GitHubIntegration(integration, source=EGRESS_SOURCE, priority=priority)
    return GitHubFilesFetcher.from_integration(github, priority=priority)


def repo_files(team: Team, repository: str, *, source_id: str, priority: Priority) -> ProbeableRepoFiles:
    """The reader for this repository's ownership files, authenticated where the team allows it.

    ``source_id`` is the source the caller resolved this repository from (see
    ``CuratedGitHubSource.source_id``), and the only source a credential may come from here. Pass an
    empty string for a read that has no selected source; it falls back like a source with no
    credential does.
    """
    credential = warehouse_sources.github_source_credential(team_id=team.pk, source_id=source_id) if source_id else None
    if credential is not None:
        fetcher = _fetcher_for_credential(team.pk, credential, priority=priority)
        if fetcher is not None:
            return AuthenticatedRepoFiles(repository, fetcher)
    return fetcher_for_team(team.pk, repository, priority=priority)
