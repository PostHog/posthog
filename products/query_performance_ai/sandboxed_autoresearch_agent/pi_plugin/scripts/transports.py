"""ClickHouse transport for autoresearch campaigns.

The coordinator's HTTP server is the only transport — one wire format,
one auth path, no direct-to-CH option. Whether the bytes ultimately land
on the test cluster (via Metabase) or on a local ClickHouse (via
sync_execute) is the coordinator's business; the sandbox never knows.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


def _require_http_url(url: str) -> None:
    """URLs come from `adapter.json` / env; urllib also speaks `file://`/`ftp://`."""
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in _ALLOWED_URL_SCHEMES:
        raise ValueError(f"transport URL scheme {scheme!r} not allowed (must be http/https): {url!r}")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Sealing the redirect-bypass for `_require_http_url` (e.g. 302 → file://)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, f"refusing to follow redirect to {newurl!r}", headers, fp)


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler())


@dataclass(frozen=True)
class TransportResult:
    """Mirrors the `metrics.json` contract so callers can write it directly."""

    result_bytes: bytes
    elapsed_ms: float
    rows_read: int | None
    bytes_read: int | None
    query_id: str | None
    stdout: str


class TransportError(RuntimeError):
    def __init__(self, message: str, *, elapsed_ms: float, stdout: str):
        super().__init__(message)
        self.elapsed_ms = elapsed_ms
        self.stdout = stdout


def load_transport(config: dict[str, Any]) -> CoordinatorTransport:
    """`type` leaves room for future transports without a workspace-format migration."""
    kind = config.get("type")
    if kind != "coordinator":
        raise ValueError(f'adapter.json "type" must be "coordinator" (got {kind!r})')
    url = config.get("url")
    token = config.get("token")
    if not url:
        raise ValueError('adapter type "coordinator" requires a "url" field')
    if not token:
        raise ValueError('adapter type "coordinator" requires a "token" field')
    return CoordinatorTransport(base_url=url, token=token)


class CoordinatorTransport:
    """POST SQL to the coordinator's ``/v1/run`` endpoint and unwrap the response.

    Config shape::

        {
          "type": "coordinator",
          "url": "http://host.docker.internal:8765",
          "token": "<random per-coordinator-run token>"
        }
    """

    def __init__(self, *, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def run(self, sql: str, *, timeout_s: int = 310) -> TransportResult:
        endpoint = f"{self.base_url}/v1/run"
        _require_http_url(endpoint)
        body = json.dumps({"sql": sql, "timeout_s": min(timeout_s, 600)}).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )

        start = time.monotonic()
        try:
            # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            with _NO_REDIRECT_OPENER.open(req, timeout=timeout_s) as resp:  # noqa: S310
                response_body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            detail = e.read().decode("utf-8", "replace")[:2000]
            raise TransportError(
                f"coordinator {e.code}: {detail}",
                elapsed_ms=elapsed_ms,
                stdout=str(e.headers),
            ) from e
        except (urllib.error.URLError, TimeoutError) as e:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            raise TransportError(
                f"coordinator transport failure: {e}",
                elapsed_ms=elapsed_ms,
                stdout="",
            ) from e
        round_trip_ms = (time.monotonic() - start) * 1000.0

        try:
            data = json.loads(response_body)
        except json.JSONDecodeError as e:
            raise TransportError(
                f"coordinator returned non-JSON response: {response_body[:500]}",
                elapsed_ms=round_trip_ms,
                stdout="",
            ) from e

        # Server-side elapsed excludes network latency; prefer it over round-trip.
        elapsed_ms = data.get("elapsed_ms")
        if not isinstance(elapsed_ms, int | float):
            elapsed_ms = round_trip_ms

        query_id = data.get("query_id")
        return TransportResult(
            result_bytes=_rows_to_jsonl_bytes(data.get("result")),
            elapsed_ms=float(elapsed_ms),
            rows_read=data.get("rows_read") if isinstance(data.get("rows_read"), int) else None,
            bytes_read=data.get("bytes_read") if isinstance(data.get("bytes_read"), int) else None,
            query_id=query_id if isinstance(query_id, str) else None,
            stdout=f"rows_returned={data.get('rows_returned')} query_id={query_id}",
        )


def _rows_to_jsonl_bytes(rows: Any) -> bytes:
    if not isinstance(rows, list) or not rows:
        return b""
    lines = [json.dumps(row, separators=(",", ":"), sort_keys=True) for row in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")
