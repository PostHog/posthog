import structlog

from posthog.models.team import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.engineering_analytics.backend.facade.contracts import GitHubSourceNotConnectedError
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.signals.contracts import CISignalFinding
from products.engineering_analytics.backend.logic.signals.detectors import detect_all
from products.engineering_analytics.backend.logic.sources import list_github_sources

logger = structlog.get_logger(__name__)


def detect_for_source(team: Team, source_id: str, *, user_access_control: UserAccessControl) -> list[CISignalFinding]:
    """Findings across every synced repo of one GitHub source, or ``[]`` while its tables sync or
    once access is revoked. Raises when detection failed for every scanned repo."""
    synced_repos = [
        source.repo
        for source in list_github_sources(team=team, user_access_control=user_access_control)
        if source.id == source_id and source.synced
    ]
    findings: list[CISignalFinding] = []
    errors: list[Exception] = []
    attempted = 0
    for repo in synced_repos:
        try:
            curated = CuratedGitHubSource.for_team(
                team, source_id=source_id, repo=repo, user_access_control=user_access_control
            )
        except GitHubSourceNotConnectedError:
            continue
        attempted += 1
        # One repo's failure must not abort the other repos of the source. When every scanned repo
        # failed, the last error is raised below so that the activity retries, because an empty
        # result would read as healthy CI.
        try:
            findings.extend(detect_all(curated))
        except Exception as err:
            logger.exception("ci_signal_detect_repo_failed", source_id=source_id, repo=repo)
            errors.append(err)
    if attempted and len(errors) == attempted:
        raise errors[-1]
    return findings
