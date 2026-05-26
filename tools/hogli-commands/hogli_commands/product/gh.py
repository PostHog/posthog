"""GitHub API helpers with caching."""

from __future__ import annotations

import shutil
import subprocess

_team_slugs: set[str] | None = None
_fetch_err: str = ""
_fetch_attempted: bool = False


def get_team_slugs(repo: str = "PostHog/posthog") -> tuple[set[str] | None, str]:
    """Fetch the GitHub team slugs that have access to ``repo``. Cached after the first call.

    Uses ``/repos/{repo}/teams`` rather than ``/orgs/{org}/teams`` for two reasons:
      1. It matches the exact set that ``POST /pulls/{n}/requested_reviewers`` accepts —
         a team has to be a *collaborator on the repo*, not merely exist in the org.
      2. It only needs the default ``GITHUB_TOKEN`` ``contents: read`` scope, so CI can
         validate without provisioning an org-scoped app token.

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
            ["gh", "api", f"repos/{repo}/teams", "--paginate", "--jq", ".[].slug"],
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
