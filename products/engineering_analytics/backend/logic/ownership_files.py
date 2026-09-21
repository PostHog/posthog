"""Where the credential for reading a repository's ownership files comes from.

Engineering analytics reports on a repository the team already connected as a warehouse source, so
that source holds a credential for it. Using it is what lets a private repository resolve at all.
The credential comes from the one source the read is already scoped to, never from a walk over the
team's other sources: a source the caller may not access can list the same repository, and reading
with its credential would hand the caller data the per-source warehouse RBAC denies them. A read
that has no selected source, or whose source holds no usable credential, falls back to the team's
GitHub integration, and then to the anonymous public reader.
"""

import structlog

from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.team import Team
from posthog.ownership.github_files import AuthenticatedRepoFiles, GitHubFilesFetcher, fetcher_for_team

from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.facade.source_management import GithubSourceConfig
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

from .ownership import ProbeableRepoFiles

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


def _fetcher_for_source(
    source: ExternalDataSource, config: GithubSourceConfig, *, priority: Priority
) -> GitHubFilesFetcher | None:
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


def _selected_source(team: Team, source_id: str) -> ExternalDataSource | None:
    """The source the read is scoped to, or None when it is gone.

    ``source_id`` comes from a resolve the caller was authorized for, so it needs no second access
    check. The team and type filters keep a stale or crafted id from reaching another team's source.
    """
    return (
        ExternalDataSource.objects.filter(team_id=team.pk, id=source_id, source_type=ExternalDataSourceType.GITHUB)
        .exclude(deleted=True)
        .first()
    )


def repo_files(team: Team, repository: str, *, source_id: str, priority: Priority) -> ProbeableRepoFiles:
    """The reader for this repository's ownership files, authenticated where the team allows it.

    ``source_id`` is the source the caller resolved this repository from (see
    ``CuratedGitHubSource.source_id``), and the only source a credential may come from here. Pass an
    empty string for a read that has no selected source; it falls back like a source with no
    credential does.
    """
    source = _selected_source(team, source_id) if source_id else None
    if source is not None:
        config = _source_config(source)
        if config is not None:
            fetcher = _fetcher_for_source(source, config, priority=priority)
            if fetcher is not None:
                return AuthenticatedRepoFiles(repository, fetcher)
    return fetcher_for_team(team.pk, repository, priority=priority)
