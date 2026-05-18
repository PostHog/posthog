"""GitHub API helpers with caching."""

from __future__ import annotations

_team_slugs: set[str] | None = None
_fetch_err: str = ""
_fetch_attempted: bool = False


def get_team_slugs(org: str = "PostHog") -> tuple[set[str] | None, str]:
    """Fetch GitHub team slugs for an org. Cached after first call.

    Returns (slugs, error_message). slugs is None when the fetch failed;
    error_message explains why.
    """
    global _team_slugs, _fetch_err, _fetch_attempted

    if _fetch_attempted:
        return _team_slugs, _fetch_err

    _fetch_attempted = True

    import shutil
    import subprocess

    if not shutil.which("gh"):
        _fetch_err = "gh CLI not found — install it to validate owner team slugs"
        return None, _fetch_err

    try:
        result = subprocess.run(
            ["gh", "api", f"orgs/{org}/teams", "--paginate", "--jq", ".[].slug"],
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
