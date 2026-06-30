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


def detect_for_team(team: Team) -> list[CISignalFinding]:
    """All CI signal findings for a team, or ``[]`` when it has no usable GitHub warehouse source."""
    try:
        curated = CuratedGitHubSource.for_team(team)
    except GitHubSourceNotConnectedError:
        # Enrolled but no usable GitHub source yet — nothing to detect, not an error.
        return []
    return detect_all(curated)
