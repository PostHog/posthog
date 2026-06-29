"""Fetch a GitHub Actions job-log archive.

``GET /repos/{repo}/actions/jobs/{job_id}/logs`` 302-redirects to a short-lived
``githubusercontent.com`` archive (plain text, can be MBs). The host is fixed and trusted, so
following the redirect is fine (no SSRF surface). Rate limits surface as ``GitHubRateLimitError`` so
the Temporal retry honors the reset.
"""

import requests

from posthog.models.integration import GITHUB_API_VERSION, _is_safe_github_repo_path, raise_if_github_rate_limited

_GITHUB_API = "https://api.github.com"
_BASE_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": GITHUB_API_VERSION}


def fetch_job_log(repo: str, job_id: int, access_token: str, *, timeout: int = 60) -> str | None:
    """Return the job's full log text, or None if GitHub has purged it (404 — expected for old jobs)."""
    if not _is_safe_github_repo_path(repo):
        # repo is team-writable source config; reject anything but plain owner/repo so a crafted
        # value can't steer this authenticated request to a different GitHub endpoint.
        raise ValueError(f"Unsafe GitHub repo path: {repo!r}")
    url = f"{_GITHUB_API}/repos/{repo}/actions/jobs/{job_id}/logs"
    headers = {**_BASE_HEADERS, "Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    raise_if_github_rate_limited(response)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.text
