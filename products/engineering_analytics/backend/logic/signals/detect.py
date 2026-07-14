"""Per-team detection entrypoint for the CI-signals coordinator.

The enabling user's ``UserAccessControl`` is the userless sweep's only read authorization.
Synchronous (HogQL reads) — the activity wraps it in ``database_sync_to_async``.
"""

from posthog.models.team import Team
from posthog.rbac.user_access_control import UserAccessControl

from products.engineering_analytics.backend.facade.contracts import GitHubSourceNotConnectedError
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.signals.contracts import CISignalFinding
from products.engineering_analytics.backend.logic.signals.detectors import detect_all


def detect_for_source(team: Team, source_id: str, *, user_access_control: UserAccessControl) -> list[CISignalFinding]:
    """Findings for one GitHub source; ``[]`` while its tables sync or once access is revoked."""
    try:
        curated = CuratedGitHubSource.for_team(team, source_id=source_id, user_access_control=user_access_control)
    except GitHubSourceNotConnectedError:
        return []
    return detect_all(curated)
