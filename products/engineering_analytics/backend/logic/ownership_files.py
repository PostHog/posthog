"""Where the credential for reading a repository's ownership files comes from.

Engineering analytics reports on a repository the team already connected as a warehouse source, so
that source holds a credential for it. Using it is what lets a private repository resolve at all.
A repository no source lists falls back to the team's GitHub integration, and then to the anonymous
public reader.
"""

import structlog

from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.team import Team
from posthog.ownership.github_files import AuthenticatedRepoFiles, GitHubFilesFetcher, fetcher_for_team
from posthog.ownership.repo_files import RepoFiles

from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.facade.source_management import GithubSourceConfig

from .sources import _configured_repositories, _github_sources

logger = structlog.get_logger(__name__)


def _source_config(source: ExternalDataSource) -> GithubSourceConfig | None:
    """``job_inputs`` is an ``EncryptedJSONField`` that can hold any JSON value, and a half-written
    source is a normal state, so an unreadable config is no reason to fail the whole board."""
    job_inputs = source.job_inputs
    if not isinstance(job_inputs, dict):
        return None
    try:
        return GithubSourceConfig.from_dict(job_inputs)
    except Exception:
        logger.warning("engineering_analytics.ownership_source_config_unreadable", source_id=str(source.pk))
        return None


def _fetcher_for_source(source: ExternalDataSource, *, priority: Priority) -> GitHubFilesFetcher | None:
    config = _source_config(source)
    if config is None:
        return None
    auth = config.auth_method
    if auth.selection == "pat":
        if not auth.personal_access_token:
            return None
        # The token is the customer's own, on the customer's own GitHub budget, so it names no
        # installation for the egress limiter to gate on.
        return GitHubFilesFetcher.from_token(auth.personal_access_token, priority=priority)
    if auth.github_integration_id is None:
        return None
    integration = Integration.objects.filter(
        team_id=source.team_id, id=auth.github_integration_id, kind="github"
    ).first()
    if integration is None:
        return None
    return GitHubFilesFetcher.from_integration(GitHubIntegration(integration), priority=priority)


def repo_files(team: Team, repository: str, *, priority: Priority) -> RepoFiles:
    """The reader for this repository's ownership files, authenticated where the team allows it."""
    wanted = repository.casefold()
    for source in _github_sources(team):
        if wanted not in {name.casefold() for name in _configured_repositories(source)}:
            continue
        fetcher = _fetcher_for_source(source, priority=priority)
        if fetcher is not None:
            return AuthenticatedRepoFiles(repository, fetcher)
    return fetcher_for_team(team.pk, repository, priority=priority)
