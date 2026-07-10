"""Pre-flight GitHub repository probe for wizard cloud runs.

A wizard cloud run is bot-authored, so its sandbox clone authenticates with the team's
first GitHub integration (see ``Task._build_task``). When that installation cannot access
the requested repository, the run only fails minutes later inside the sandbox as a clone
error ("remote: Repository not found"), burning a full sandbox boot. This probe performs
the same access check up front, with the same credential resolution the clone will use,
so the kickoff endpoint can reject a doomed run in seconds instead.

The probe also mirrors the wizard CLI's framework auto-detection inputs: the CLI only
looks at manifests at the repository root, so a root with none of them fails the run
deterministically ("Could not auto-detect your framework for this project"). Deriving
that from a single root listing lets the kickoff endpoint fail those runs up front too.
"""

import re
import logging
from dataclasses import dataclass
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

# Root manifests the wizard CLI's framework auto-detection keys off (package.json deps and
# Python/Go manifests). A root with none of these makes the sandbox run fail deterministically.
WIZARD_DETECTABLE_MANIFEST_FILES = frozenset(
    {
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "setup.py",
        "Pipfile",
        "go.mod",
    }
)


class WizardRepoAccess(Enum):
    ACCESSIBLE = "accessible"
    INACCESSIBLE = "inaccessible"
    UNKNOWN = "unknown"


class WizardRepositoryInaccessibleError(Exception):
    """The repository doesn't exist or the team's GitHub installation cannot access it."""


class WizardFrameworkUndetectableError(Exception):
    """The repository root has no manifest the wizard's framework auto-detection can use."""


@dataclass(frozen=True)
class WizardRepoProbe:
    access: WizardRepoAccess
    # None means "could not tell" (listing failed or wasn't attempted); only an explicit
    # False - a successful root listing with no supported manifest - should block a run.
    framework_detectable: bool | None = None


def probe_wizard_repository(team: Team, repository: str) -> WizardRepoProbe:
    """Probe ``repository`` (``owner/repo``) with the team's GitHub installation.

    Resolves the integration exactly like ``Task._build_task`` binds ``github_integration``
    for a bot-authored run (first team GitHub integration), so the answer matches what the
    sandbox clone will experience. Fail-open by design: rate limits, timeouts, and any
    unexpected response map to ``UNKNOWN`` access / ``None`` detectability — only a
    definitive 404 reports ``INACCESSIBLE``, and only a successful root listing with no
    supported manifest reports ``framework_detectable=False``. Never raises.
    """
    if not _SAFE_REPO_PATH_RE.fullmatch(repository) or ".." in repository:
        # Not a name that can exist on GitHub — the clone would fail identically.
        return WizardRepoProbe(access=WizardRepoAccess.INACCESSIBLE)
    try:
        integration = Integration.objects.filter(team=team, kind="github").first()
        if integration is None:
            # No team installation to probe with; ``_build_task`` owns this case (user
            # integration fallback or a hard "no GitHub integration" error).
            return WizardRepoProbe(access=WizardRepoAccess.UNKNOWN)
        github = GitHubIntegration(integration, source=_PROBE_SOURCE)
        response = github.api_request("GET", f"/repos/{repository}", endpoint="/repos/{owner}/{repo}")
    except GitHubIntegrationError:
        logger.warning("Wizard repo probe failed for team %s", team.id, exc_info=True)
        return WizardRepoProbe(access=WizardRepoAccess.UNKNOWN)
    except Exception:
        logger.exception("Unexpected wizard repo probe failure for team %s", team.id)
        return WizardRepoProbe(access=WizardRepoAccess.UNKNOWN)
    if response.status_code == 404:
        return WizardRepoProbe(access=WizardRepoAccess.INACCESSIBLE)
    if response.status_code != 200:
        return WizardRepoProbe(access=WizardRepoAccess.UNKNOWN)
    return WizardRepoProbe(
        access=WizardRepoAccess.ACCESSIBLE,
        framework_detectable=_root_framework_detectable(github, repository),
    )


def _root_framework_detectable(github: GitHubIntegration, repository: str) -> bool | None:
    """Whether the repo root holds any manifest the wizard's auto-detection can work from.

    Conservative on purpose: any failure to list the root (error, non-200, unexpected
    payload) returns ``None`` so uncertainty never blocks a run.
    """
    try:
        response = github.api_request(
            "GET",
            f"/repos/{repository}/contents",
            endpoint="/repos/{owner}/{repo}/contents/{path}",
        )
    except Exception:
        logger.warning("Wizard repo probe root listing failed for %s", repository, exc_info=True)
        return None
    if response.status_code != 200:
        return None
    try:
        entries = response.json()
    except Exception:
        return None
    if not isinstance(entries, list):
        return None
    names = {entry.get("name") for entry in entries if isinstance(entry, dict)}
    return bool(names & WIZARD_DETECTABLE_MANIFEST_FILES)
