"""Per-team detection entrypoint for the CI-signals coordinator.

Builds the curated read layer for a team and runs every detector. The sweep runs with no request
user, so the caller must pass the enabling user's ``UserAccessControl`` — that snapshot-holder's
warehouse RBAC is the sweep's only authorization to read a source (see
``list_authorized_ci_signal_sources``). Synchronous — it issues HogQL reads — so the activity
wraps it in ``database_sync_to_async``.
"""

import structlog

from posthog.models.team import Team
from posthog.rbac.user_access_control import UserAccessControl

from products.engineering_analytics.backend.facade.contracts import GitHubSourceNotConnectedError
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.signals.contracts import CISignalFinding
from products.engineering_analytics.backend.logic.signals.detectors import detect_all

logger = structlog.get_logger(__name__)


def detect_for_source(team: Team, source_id: str, *, user_access_control: UserAccessControl) -> list[CISignalFinding]:
    """CI signal findings for one GitHub source, or ``[]`` while its required tables sync.

    A source the authorizing user can't (or can no longer) access resolves as not-connected and
    yields no findings, so access revoked between discovery and detection still fails closed."""
    try:
        curated = CuratedGitHubSource.for_team(team, source_id=source_id, user_access_control=user_access_control)
    except GitHubSourceNotConnectedError:
        return []
    return detect_all(curated)
