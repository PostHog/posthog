"""Per-team detection entrypoint for the CI-signals coordinator.

Builds the curated read layer for a team and runs every detector. Userless (a system sweep with no
request user): ``CuratedGitHubSource`` bypasses per-table warehouse ACL on this path but stays
team-scoped (see ``_curated.run``). Synchronous — it issues HogQL reads — so the activity wraps it
in ``database_sync_to_async``.
"""

import structlog

from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import GitHubSourceNotConnectedError
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.signals.contracts import CISignalFinding
from products.engineering_analytics.backend.logic.signals.detectors import detect_all

logger = structlog.get_logger(__name__)


def detect_for_source(team: Team, source_id: str) -> list[CISignalFinding]:
    """CI signal findings for one GitHub source, or ``[]`` while its required tables sync."""
    try:
        curated = CuratedGitHubSource.for_team(team, source_id=source_id)
    except GitHubSourceNotConnectedError:
        return []
    return detect_all(curated)
