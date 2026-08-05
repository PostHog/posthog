"""Per-team detection entrypoint for the CI-signals coordinator.

The enabling user's ``UserAccessControl`` is the userless sweep's only read authorization.
Synchronous (HogQL reads); the activity wraps it in ``database_sync_to_async``.
"""

import structlog

from posthog.models.team import Team
from posthog.rbac.user_access_control import UserAccessControl

from products.engineering_analytics.backend.facade.contracts import GitHubSourceNotConnectedError
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.signals.contracts import CISignalFinding
from products.engineering_analytics.backend.logic.signals.detectors import detect_all
from products.engineering_analytics.backend.logic.sources import list_github_sources

logger = structlog.get_logger(__name__)


def detect_for_source(team: Team, source_id: str, *, user_access_control: UserAccessControl) -> list[CISignalFinding]:
    """Findings for one GitHub source, scanning each synced repo: a multi-repo source contributes
    every repo it syncs, not just the one the bare resolver would pick. ``[]`` while its tables
    sync or once access is revoked. Finding source_ids are repo-qualified, so repos never collide
    in the emission ledger."""
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
        # detect_all raises only when every detector failed for this repo (a warehouse outage, say).
        # Isolate that per repo so one repo's failure doesn't abort healthy siblings of a multi-repo
        # source; if every scanned repo failed, re-raise so the activity retries rather than emitting
        # nothing that reads as healthy CI.
        try:
            findings.extend(detect_all(curated))
        except Exception as err:
            logger.exception("ci_signal_detect_repo_failed", source_id=source_id, repo=repo)
            errors.append(err)
    if attempted and len(errors) == attempted:
        raise errors[-1]
    return findings
