"""GitHub API helpers with caching."""

from __future__ import annotations

import shutil
import subprocess

_team_slugs: set[str] | None = None
_fetch_err: str = ""
_fetch_attempted: bool = False


_ORG = "PostHog"


def get_team_slugs() -> tuple[set[str] | None, str]:
    """Fetch GitHub team slugs visible in the PostHog org. Cached after the first call.

    Uses ``/orgs/{org}/teams`` (requires ``members: read``) rather than the
    repo-collaborator endpoint ``/repos/{repo}/teams``. The repo endpoint would
    be the tighter check semantically (the reviewer assignment API only accepts
    repo collaborator teams), but the assign-reviewers GitHub App doesn't have
    the scope for it. The "team exists in org but lacks repo access" gap is
    covered defensively by assign-reviewers.js's 422 fallback, which retries
    each team individually and logs the bad slugs.

    Returns ``(slugs, error_message)``. ``slugs`` is ``None`` when the fetch failed.
    """
    global _team_slugs, _fetch_err, _fetch_attempted

    if _fetch_attempted:
        return _team_slugs, _fetch_err

    _fetch_attempted = True

    if not shutil.which("gh"):
        _fetch_err = "gh CLI not found — install it to validate owner team slugs"
        return None, _fetch_err

    try:
        result = subprocess.run(
            ["gh", "api", f"orgs/{_ORG}/teams", "--paginate", "--jq", ".[].slug"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            _team_slugs = set(result.stdout.strip().split("\n"))
            return _team_slugs, ""
        _fetch_err = f"gh api failed (rc={result.returncode}): {result.stderr.strip()}"
        return None, _fetch_err
    except subprocess.TimeoutExpired:
        _fetch_err = "gh api timed out after 15s"
        return None, _fetch_err
