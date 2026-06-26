"""Fetch a GitHub Actions job-log archive.

``GET /repos/{repo}/actions/jobs/{job_id}/logs`` 302-redirects to a short-lived
``githubusercontent.com`` archive (plain text, can be MBs). We hit a fixed, trusted GitHub host
and follow the one redirect to GitHub's own archive host, so a plain redirect-following request is
appropriate here (no user-supplied host, so the SSRF-hardened no-redirect session the data-imports
sources use isn't needed). GitHub's rate-limit signal is surfaced as ``GitHubRateLimitError`` so the
Temporal retry honors the reset rather than hammering the shared budget.
"""

import requests

from posthog.models.integration import raise_if_github_rate_limited

_GITHUB_API = "https://api.github.com"
_BASE_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def fetch_job_log(repo: str, job_id: int, access_token: str, *, timeout: int = 60) -> str | None:
    """Return the job's full log text, or None if GitHub no longer has it.

    GitHub expires Actions logs (404 once purged), which is an expected outcome for older jobs —
    the caller should treat None as "nothing to emit", not an error.
    """
    url = f"{_GITHUB_API}/repos/{repo}/actions/jobs/{job_id}/logs"
    headers = {**_BASE_HEADERS, "Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    raise_if_github_rate_limited(response)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.text
