"""Pre-flight checks run before a wizard cloud run reserves a sandbox.

Two kickoff inputs decide the run's outcome before any code executes: whether the team's GitHub
installation can reach the repository at all, and whether the repository holds any project manifest
the wizard's framework detection keys off. Both are answerable from two GitHub reads, and both are
otherwise only discovered inside the sandbox, minutes in, as a clone error or as the wizard aborting
with "Could not auto-detect your framework for this project".

Everything here is fail-open: a check reports a negative only on an unambiguous answer, so any
degraded GitHub response (rate limit, timeout, truncated tree, unexpected payload) leaves the run
exactly as it is today.
"""

import re
import logging
from dataclasses import dataclass
from enum import Enum

import requests

from posthog.models.integration import GitHubIntegration
from posthog.models.team import Team

from products.tasks.backend.logic.services.sandbox import is_public_sandbox_repo
from products.tasks.backend.models import resolve_team_github_integration

logger = logging.getLogger(__name__)

_PREFLIGHT_SOURCE = "tasks"
_GITHUB_REQUEST_TIMEOUT_SECONDS = 5

# A plain ``owner/repo`` and nothing else. The kickoff serializer only checks the two-segment shape,
# so this is what keeps ``..``/``?``/``#`` in team-supplied input from steering the authenticated
# reads below at a different GitHub endpoint.
_SAFE_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
# Same containment rule for the ref, which is also interpolated into a path, with ``/`` allowed for
# namespaced branches ("feature/x").
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9._/-]+$")

# Basenames of every project manifest the wizard identifies a framework by. Mirrors PROJECT_MANIFESTS
# in the wizard's src/lib/detection/agentic.ts; keep the two in sync, and when in doubt add the entry
# here, since a manifest missing from this set is what turns a healthy repository into a rejection.
WIZARD_PROJECT_MANIFESTS = frozenset(
    {
        "package.json",
        "pnpm-workspace.yaml",
        "turbo.json",
        "nx.json",
        "lerna.json",
        "requirements.txt",
        "pyproject.toml",
        "setup.py",
        "Pipfile",
        "manage.py",
        "Gemfile",
        "composer.json",
        "Cargo.toml",
        "go.mod",
        "mix.exs",
        "pom.xml",
        "Package.swift",
        "Podfile",
        "project.yml",
        "project.pbxproj",
        "pubspec.yaml",
        "build.gradle",
        "build.gradle.kts",
        "settings.gradle",
        "settings.gradle.kts",
        "libs.versions.toml",
    }
)

# The one wizard manifest entry that is a glob rather than a fixed name.
_WIZARD_MANIFEST_SUFFIXES = (".csproj",)


class WizardRepositoryAccess(Enum):
    ACCESSIBLE = "accessible"
    INACCESSIBLE = "inaccessible"
    UNKNOWN = "unknown"


class WizardRepositoryInaccessibleError(Exception):
    """The repository doesn't exist or the team's GitHub installation cannot reach it."""


class WizardFrameworkUndetectableError(Exception):
    """The repository holds no manifest the wizard's framework detection can work from."""


@dataclass(frozen=True)
class WizardRepositoryPreflight:
    access: WizardRepositoryAccess
    # None means "could not tell": the listing failed, came back truncated, or was never attempted.
    # Only an explicit False may block a run.
    framework_detectable: bool | None = None


def preflight_wizard_repository(team: Team, repository: str, branch: str | None = None) -> WizardRepositoryPreflight:
    """Read ``repository`` (``owner/repo``) with the team's GitHub installation.

    Reads with ``resolve_team_github_integration``, the same helper ``Task._build_task`` binds a
    run to, so the answer is reached with the credentials the run would clone with rather than with
    some other install of the team's. ``branch`` is the ref the sandbox checks out; detectability is
    judged on that ref's tree, and on the default branch's when no branch was requested. Never
    raises.
    """
    if not _is_safe_path(repository, _SAFE_REPOSITORY_RE):
        return WizardRepositoryPreflight(access=WizardRepositoryAccess.UNKNOWN)

    if is_public_sandbox_repo(repository):
        # The sandbox clones these unauthenticated and ``_build_task`` exempts them from needing an
        # integration at all, so no installation's reach decides the run's fate. Reading them with
        # one anyway would answer a question nobody asked, and a 404 would block a healthy run.
        return WizardRepositoryPreflight(access=WizardRepositoryAccess.UNKNOWN)

    try:
        integration = resolve_team_github_integration(team)
        if integration is None:
            # Nothing to read with; ``_build_task`` owns this case (user integration fallback, or a
            # hard "no GitHub integration" error).
            return WizardRepositoryPreflight(access=WizardRepositoryAccess.UNKNOWN)
        github = GitHubIntegration(integration, source=_PREFLIGHT_SOURCE)
        response = _github_get(github, f"/repos/{repository}", endpoint="/repos/{owner}/{repo}")
    except Exception:
        logger.warning("wizard_preflight.repository_read_failed", extra={"team_id": team.id}, exc_info=True)
        return WizardRepositoryPreflight(access=WizardRepositoryAccess.UNKNOWN)

    if response.status_code == 404:
        return WizardRepositoryPreflight(access=WizardRepositoryAccess.INACCESSIBLE)
    if response.status_code != 200:
        return WizardRepositoryPreflight(access=WizardRepositoryAccess.UNKNOWN)

    return WizardRepositoryPreflight(
        access=WizardRepositoryAccess.ACCESSIBLE,
        framework_detectable=_framework_detectable(github, repository, branch or _default_branch(response)),
    )


def _is_safe_path(value: str, pattern: re.Pattern[str]) -> bool:
    return bool(pattern.fullmatch(value)) and ".." not in value


def _github_get(
    github: GitHubIntegration,
    path: str,
    *,
    endpoint: str,
    params: dict[str, str | int] | None = None,
) -> requests.Response:
    return github.api_request("GET", path, endpoint=endpoint, params=params, timeout=_GITHUB_REQUEST_TIMEOUT_SECONDS)


def _default_branch(repository_response: requests.Response) -> str | None:
    try:
        payload = repository_response.json()
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    default_branch = payload.get("default_branch")
    return default_branch if isinstance(default_branch, str) and default_branch else None


def _framework_detectable(github: GitHubIntegration, repository: str, ref: str | None) -> bool | None:
    """Whether ``ref``'s tree holds any manifest the wizard's framework detection can work from.

    The wizard globs the whole checkout for manifests, not just the root, so this matches on every
    blob in the recursive tree. Returns None on anything that leaves the tree in doubt, a
    ``truncated`` response included: a partial tree can hide the repository's only manifest.
    """
    if ref is None or not _is_safe_path(ref, _SAFE_REF_RE):
        return None
    try:
        response = _github_get(
            github,
            f"/repos/{repository}/git/trees/{ref}",
            endpoint="/repos/{owner}/{repo}/git/trees/{tree_sha}",
            params={"recursive": 1},
        )
    except Exception:
        logger.warning("wizard_preflight.tree_read_failed", extra={"repository": repository}, exc_info=True)
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("truncated") is not False:
        return None
    entries = payload.get("tree")
    if not isinstance(entries, list):
        return None
    return any(
        _is_wizard_manifest(entry["path"])
        for entry in entries
        if isinstance(entry, dict) and entry.get("type") == "blob" and isinstance(entry.get("path"), str)
    )


def _is_wizard_manifest(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name in WIZARD_PROJECT_MANIFESTS or name.endswith(_WIZARD_MANIFEST_SUFFIXES)
