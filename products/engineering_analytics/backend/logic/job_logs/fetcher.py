"""Fetch a GitHub Actions job-log archive.

``GET /repos/{repo}/actions/jobs/{job_id}/logs`` 302-redirects to a short-lived
``githubusercontent.com`` archive (plain text, can be MBs). The host is fixed and trusted, so
following the redirect is fine (no SSRF surface). Rate limits surface as ``GitHubRateLimitError`` so
the Temporal retry honors the reset.
"""

import requests

from posthog.egress.github.transport import GITHUB_API_VERSION, raise_if_github_rate_limited
from posthog.models.integration import _is_safe_github_repo_path

_GITHUB_API = "https://api.github.com"
_BASE_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": GITHUB_API_VERSION}
# A connected repo's failed job can print an arbitrarily large log; cap the bytes we pull into memory
# before thinning (the thinner only caps line count, after the bytes are already decoded).
_MAX_LOG_BYTES = 20 * 1024 * 1024


def fetch_job_log(
    repo: str, job_id: int, access_token: str, *, timeout: int = 60, max_bytes: int = _MAX_LOG_BYTES
) -> str | None:
    """Return the job's log text (capped at ``max_bytes``), or None if GitHub purged it (404)."""
    if not _is_safe_github_repo_path(repo):
        # repo is team-writable source config; reject anything but plain owner/repo so a crafted
        # value can't steer this authenticated request to a different GitHub endpoint.
        raise ValueError(f"Unsafe GitHub repo path: {repo!r}")
    url = f"{_GITHUB_API}/repos/{repo}/actions/jobs/{job_id}/logs"
    headers = {**_BASE_HEADERS, "Authorization": f"Bearer {access_token}"}
    # Stream within the byte budget so a pathological log can't OOM the worker. Keep a bounded head
    # AND a rolling tail: failures surface at the end (the run summary), so a head-only cap could drop
    # the very lines thin_log needs if a job pads the start with noise.
    with requests.get(url, headers=headers, timeout=timeout, allow_redirects=True, stream=True) as response:
        raise_if_github_rate_limited(response)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        head = bytearray()
        tail = bytearray()
        half = max(1, max_bytes // 2)
        truncated = False
        for chunk in response.iter_content(chunk_size=65536):
            if len(head) < half:
                room = half - len(head)
                head.extend(chunk[:room])
                chunk = chunk[room:]
            if chunk:
                tail.extend(chunk)
                if len(tail) > half:
                    truncated = True
                    del tail[:-half]  # keep only the most recent `half` bytes
        if truncated:
            return (bytes(head) + b"\n... [log truncated] ...\n" + bytes(tail)).decode("utf-8", errors="replace")
        return (bytes(head) + bytes(tail)).decode("utf-8", errors="replace")
