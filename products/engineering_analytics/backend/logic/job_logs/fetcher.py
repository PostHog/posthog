"""Fetch a failed CI job's log from GitHub Actions or Depot CI.

``GET /repos/{repo}/actions/jobs/{job_id}/logs`` 302-redirects to a short-lived
``githubusercontent.com`` archive (plain text, can be MBs). The host is fixed and trusted, so
following the redirect is fine (no SSRF surface). Rate limits surface as ``GitHubRateLimitError`` so
the Temporal retry honors the reset.
"""

import datetime as dt
import contextlib
from typing import Any

import requests
from temporalio.exceptions import ApplicationError

from posthog.egress.github.transport import github_request, raise_if_github_rate_limited
from posthog.models.integration.github import _is_safe_github_repo_path

_GITHUB_API = "https://api.github.com"
_DEPOT_JOB_ATTEMPT_LOGS = "https://api.depot.dev/depot.ci.v1.CIService/GetJobAttemptLogs"
# A connected repo's failed job can print an arbitrarily large log; cap the bytes we pull into memory
# before thinning (the thinner only caps line count, after the bytes are already decoded).
_MAX_LOG_BYTES = 20 * 1024 * 1024


class _HeadAndTail:
    """The first and the last ``max_bytes // 2`` bytes of a log that arrives in chunks.

    Stream within the byte budget so a pathological log can't OOM the worker. Keep a bounded head
    AND a rolling tail: failures surface at the end (the run summary), so a head-only cap could drop
    the very lines thin_log needs if a job pads the start with noise.
    """

    def __init__(self, max_bytes: int) -> None:
        self._half = max(1, max_bytes // 2)
        self._head = bytearray()
        self._tail = bytearray()
        self._truncated = False

    def extend(self, chunk: bytes) -> None:
        if len(self._head) < self._half:
            room = self._half - len(self._head)
            self._head.extend(chunk[:room])
            chunk = chunk[room:]
        if chunk:
            self._tail.extend(chunk)
            if len(self._tail) > self._half:
                self._truncated = True
                del self._tail[: -self._half]  # keep only the most recent `half` bytes

    def text(self) -> str:
        middle = b"\n... [log truncated] ...\n" if self._truncated else b""
        return (bytes(self._head) + middle + bytes(self._tail)).decode("utf-8", errors="replace")


def fetch_job_log(
    repo: str, job_id: int, access_token: str, *, timeout: int = 60, max_bytes: int = _MAX_LOG_BYTES
) -> str | None:
    """Return the job's log text (capped at ``max_bytes``), or None if GitHub purged it (404)."""
    if not _is_safe_github_repo_path(repo):
        # repo is team-writable source config; reject anything but plain owner/repo so a crafted
        # value can't steer this authenticated request to a different GitHub endpoint.
        raise ValueError(f"Unsafe GitHub repo path: {repo!r}")
    url = f"{_GITHUB_API}/repos/{repo}/actions/jobs/{job_id}/logs"
    # Identity-blind on purpose: the activity already gated this call against the installation
    # budget before dispatch, so gating here again would consume the budget twice.
    with contextlib.closing(
        github_request(
            "GET",
            url,
            source="job_logs",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
            allow_redirects=True,
            stream=True,
        )
    ) as response:
        raise_if_github_rate_limited(response)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        log = _HeadAndTail(max_bytes)
        for chunk in response.iter_content(chunk_size=65536):
            log.extend(chunk)
        return log.text()


def _depot_line_text(line: dict[str, Any]) -> str:
    # Rendered as a GitHub log line, `<RFC3339 UTC timestamp> <body>`, so the emitter reads the
    # line's timestamp the same way for both engines. Depot sends the int64 `timestampMs` as a
    # JSON string and omits it when it is zero.
    body = str(line.get("body", ""))
    timestamp_ms = int(line.get("timestampMs") or 0)
    if not timestamp_ms:
        return body
    timestamp = dt.datetime.fromtimestamp(timestamp_ms / 1000, dt.UTC).isoformat(timespec="milliseconds")
    return f"{timestamp.removesuffix('+00:00')}Z {body}"


def _retry_after(response: requests.Response) -> dt.timedelta | None:
    value = response.headers.get("Retry-After", "")
    return dt.timedelta(seconds=int(value)) if value.isdigit() else None


def fetch_depot_job_log(
    attempt_id: str,
    api_token: str,
    *,
    timeout: int = 60,
    max_bytes: int = _MAX_LOG_BYTES,
    max_read_bytes: int = 4 * _MAX_LOG_BYTES,
) -> str | None:
    """Return the Depot CI attempt's log text (capped at ``max_bytes``), or None if Depot has none (404).

    ``api_token`` is the team's own Depot organization token, so no shared PostHog egress budget
    applies. A 429 passes Depot's ``Retry-After`` to the Temporal retry instead.

    The pages stop after ``max_read_bytes`` of responses, so a job that prints an unbounded log
    cannot hold a worker in the download. The log then keeps its head and the tail read so far.
    """
    log = _HeadAndTail(max_bytes)
    read_budget = max_read_bytes
    request = {"attemptId": attempt_id}
    with requests.Session() as session:
        session.headers["Authorization"] = f"Bearer {api_token}"
        while True:
            response = session.post(_DEPOT_JOB_ATTEMPT_LOGS, json=request, timeout=timeout)
            if response.status_code == 404:
                return None
            if response.status_code == 429:
                raise ApplicationError(
                    "Depot rate limited the job log fetch",
                    type="DepotRateLimited",
                    next_retry_delay=_retry_after(response),
                )
            response.raise_for_status()
            read_budget -= len(response.content)
            page = response.json()
            for line in page.get("lines", []):
                log.extend(f"{_depot_line_text(line)}\n".encode())
            page_token = page.get("nextPageToken")
            if not page_token:
                return log.text()
            if read_budget <= 0:
                log.extend(b"\n... [log download stopped at the read budget] ...\n")
                return log.text()
            request = {"attemptId": attempt_id, "pageToken": page_token}
