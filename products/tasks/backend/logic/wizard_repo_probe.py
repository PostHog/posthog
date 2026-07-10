"""Pre-flight GitHub repository probe for wizard cloud runs.

A wizard cloud run is bot-authored, so its sandbox clone authenticates with the team's
first GitHub integration (see ``Task._build_task``). When that installation cannot access
the requested repository, the run only fails minutes later inside the sandbox as a clone
error ("remote: Repository not found"), burning a full sandbox boot. This probe performs
the same access check up front, with the same credential resolution the clone will use,
so the kickoff endpoint can reject a doomed run in seconds instead.
"""

import re
import logging
from enum import Enum

from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.team import Team

logger = logging.getLogger(__name__)

_PROBE_SOURCE = "tasks"

# Mirrors ``posthog.models.integration._GITHUB_REPO_PATH_RE``: a plain ``owner/repo`` only,
# so team-supplied input (``..``, ``?``, ``#``) can never steer the authenticated GET below
# to a different GitHub endpoint.
_SAFE_REPO_PATH_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


class WizardRepoAccess(Enum):
    ACCESSIBLE = "accessible"
    INACCESSIBLE = "inaccessible"
    UNKNOWN = "unknown"


class WizardRepositoryInaccessibleError(Exception):
    """The repository doesn't exist or the team's GitHub installation cannot access it."""


def probe_wizard_repository_access(team: Team, repository: str) -> WizardRepoAccess:
    """Check whether the team's GitHub installation can access ``repository`` (``owner/repo``).

    Resolves the integration exactly like ``Task._build_task`` binds ``github_integration``
    for a bot-authored run (first team GitHub integration), so the answer matches what the
    sandbox clone will experience. Fail-open by design: rate limits, timeouts, and any
    unexpected response map to ``UNKNOWN`` — only a definitive 404 reports ``INACCESSIBLE``.
    Never raises.
    """
    if not _SAFE_REPO_PATH_RE.fullmatch(repository) or ".." in repository:
        # Not a name that can exist on GitHub — the clone would fail identically.
        return WizardRepoAccess.INACCESSIBLE
    try:
        integration = Integration.objects.filter(team=team, kind="github").first()
        if integration is None:
            # No team installation to probe with; ``_build_task`` owns this case (user
            # integration fallback or a hard "no GitHub integration" error).
            return WizardRepoAccess.UNKNOWN
        github = GitHubIntegration(integration, source=_PROBE_SOURCE)
        response = github.api_request("GET", f"/repos/{repository}", endpoint="/repos/{owner}/{repo}")
    except GitHubIntegrationError:
        logger.warning("Wizard repo probe failed for team %s", team.id, exc_info=True)
        return WizardRepoAccess.UNKNOWN
    except Exception:
        logger.exception("Unexpected wizard repo probe failure for team %s", team.id)
        return WizardRepoAccess.UNKNOWN
    if response.status_code == 200:
        return WizardRepoAccess.ACCESSIBLE
    if response.status_code == 404:
        return WizardRepoAccess.INACCESSIBLE
    return WizardRepoAccess.UNKNOWN
