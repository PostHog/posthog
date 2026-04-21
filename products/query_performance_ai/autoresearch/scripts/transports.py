"""ClickHouse transports for autoresearch campaigns.

Each workspace's ``adapter.json`` selects a transport by ``type``. The
transports here are intentionally small wrappers — the surface area between
a campaign and ClickHouse is a single ``run(sql) -> TransportResult`` call.

Adding a new transport: subclass :class:`Transport`, register it in
:data:`_TRANSPORTS`, and document its config shape.
"""

from __future__ import annotations

import abc
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TransportResult:
    """Result of a single query execution.

    Attributes mirror the ``metrics.json`` contract so the bookkeeping scripts
    can write it directly:

      * ``result_bytes`` — raw result body (TSV by default)
      * ``elapsed_ms`` — client-side wall-clock latency
      * ``rows_read`` / ``bytes_read`` — ClickHouse-reported counters if
        available, else ``None``
      * ``stdout`` — transport-level log (headers, warnings) for debugging
    """

    result_bytes: bytes
    elapsed_ms: float
    rows_read: int | None
    bytes_read: int | None
    stdout: str


class Transport(abc.ABC):
    @abc.abstractmethod
    def run(self, sql: str, *, timeout_s: int = 30) -> TransportResult: ...


class HttpTransport(Transport):
    """Plain HTTP ClickHouse transport.

    Config shape::

        {"type": "http", "url": "http://localhost:8123", "headers": {...}}

    The SQL is POSTed as the raw request body. X-ClickHouse-Summary (if
    returned) is parsed for rows_read/bytes_read.
    """

    def __init__(self, *, url: str, headers: dict[str, str] | None = None):
        self.url = url.rstrip("/")
        self.headers = headers or {}

    def run(self, sql: str, *, timeout_s: int = 30) -> TransportResult:
        endpoint = f"{self.url}/?default_format=TSV"
        req = urllib.request.Request(
            endpoint,
            data=sql.encode("utf-8"),
            method="POST",
            headers={"Content-Type": "text/plain; charset=utf-8", **self.headers},
        )

        start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                body = resp.read()
                summary_header = resp.headers.get("X-ClickHouse-Summary") or ""
                stdout = "\n".join(f"{k}: {v}" for k, v in resp.headers.items())
        except urllib.error.HTTPError as e:
            body = e.read()
            elapsed_ms = (time.monotonic() - start) * 1000.0
            raise TransportError(
                f"ClickHouse HTTP {e.code}: {body.decode('utf-8', 'replace')[:500]}",
                elapsed_ms=elapsed_ms,
                stdout=str(e.headers),
            ) from e
        except (urllib.error.URLError, TimeoutError) as e:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            raise TransportError(
                f"ClickHouse transport failure: {e}",
                elapsed_ms=elapsed_ms,
                stdout="",
            ) from e
        elapsed_ms = (time.monotonic() - start) * 1000.0

        rows_read, bytes_read = _parse_summary(summary_header)
        return TransportResult(
            result_bytes=body,
            elapsed_ms=elapsed_ms,
            rows_read=rows_read,
            bytes_read=bytes_read,
            stdout=stdout,
        )


class TransportError(RuntimeError):
    """Raised when a transport fails to run a query."""

    def __init__(self, message: str, *, elapsed_ms: float, stdout: str):
        super().__init__(message)
        self.elapsed_ms = elapsed_ms
        self.stdout = stdout


def _parse_summary(summary: str) -> tuple[int | None, int | None]:
    if not summary:
        return None, None
    try:
        data = json.loads(summary)
    except json.JSONDecodeError:
        return None, None
    rows = data.get("read_rows")
    bytes_ = data.get("read_bytes")
    try:
        rows = int(rows) if rows is not None else None
    except (TypeError, ValueError):
        rows = None
    try:
        bytes_ = int(bytes_) if bytes_ is not None else None
    except (TypeError, ValueError):
        bytes_ = None
    return rows, bytes_


def load_transport(config: dict[str, Any]) -> Transport:
    """Build a :class:`Transport` from a parsed ``adapter.json`` config."""
    kind = config.get("type")
    if not kind:
        raise ValueError('adapter.json must set a "type" field')
    factory = _TRANSPORTS.get(kind)
    if factory is None:
        raise ValueError(
            f"unknown adapter type: {kind!r} (supported: {sorted(_TRANSPORTS)})"
        )
    return factory(config)


def _http_factory(config: dict[str, Any]) -> Transport:
    url = config.get("url")
    if not url:
        raise ValueError('adapter type "http" requires a "url" field')
    headers = config.get("headers") or {}
    if not isinstance(headers, dict):
        raise ValueError('adapter "headers" must be an object')
    return HttpTransport(url=url, headers=headers)


class PosthogProxyTransport(Transport):
    """Routes queries through PostHog's OAuth-gated ClickHouse proxy.

    Config shape::

        {
          "type": "posthog_proxy",
          "url": "https://posthog.example.com",   # base URL of the PostHog app
          "cluster": "test" | "prod",             # dispatches to /execute-test or /execute-prod
          "token": "<oauth access token>"         # must have clickhouse_perf:<cluster>_read scope
        }

    The proxy validates SQL server-side (readonly + team_id = 2 on prod), so
    this transport stays a thin shim: POST JSON, unwrap the response payload
    into a :class:`TransportResult`.
    """

    def __init__(self, *, base_url: str, cluster: str, token: str):
        if cluster not in ("test", "prod"):
            raise ValueError('posthog_proxy "cluster" must be "test" or "prod"')
        self.base_url = base_url.rstrip("/")
        self.cluster = cluster
        self.token = token

    def run(self, sql: str, *, timeout_s: int = 30) -> TransportResult:
        endpoint = f"{self.base_url}/api/query_performance_proxy/execute-{self.cluster}/"
        body = json.dumps({"sql": sql}).encode("utf-8")
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
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                response_body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            detail = e.read().decode("utf-8", "replace")[:2000]
            raise TransportError(
                f"posthog_proxy {e.code}: {detail}",
                elapsed_ms=elapsed_ms,
                stdout=str(e.headers),
            ) from e
        except (urllib.error.URLError, TimeoutError) as e:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            raise TransportError(
                f"posthog_proxy transport failure: {e}",
                elapsed_ms=elapsed_ms,
                stdout="",
            ) from e
        round_trip_ms = (time.monotonic() - start) * 1000.0

        try:
            data = json.loads(response_body)
        except json.JSONDecodeError as e:
            raise TransportError(
                f"posthog_proxy returned non-JSON response: {response_body[:500]}",
                elapsed_ms=round_trip_ms,
                stdout="",
            ) from e

        # The proxy measures elapsed_ms server-side (just the ClickHouse hop,
        # excluding network latency to the proxy). Prefer that over round-trip.
        elapsed_ms = data.get("elapsed_ms")
        if not isinstance(elapsed_ms, int | float):
            elapsed_ms = round_trip_ms

        return TransportResult(
            result_bytes=(data.get("result") or "").encode("utf-8"),
            elapsed_ms=float(elapsed_ms),
            rows_read=data.get("rows_read") if isinstance(data.get("rows_read"), int) else None,
            bytes_read=data.get("bytes_read") if isinstance(data.get("bytes_read"), int) else None,
            stdout=f"query_id={data.get('query_id')}",
        )


def _posthog_proxy_factory(config: dict[str, Any]) -> Transport:
    url = config.get("url")
    cluster = config.get("cluster")
    token = config.get("token")
    if not url:
        raise ValueError('adapter type "posthog_proxy" requires a "url" field')
    if cluster not in ("test", "prod"):
        raise ValueError('adapter type "posthog_proxy" requires "cluster" to be "test" or "prod"')
    if not token:
        raise ValueError('adapter type "posthog_proxy" requires a "token" field')
    return PosthogProxyTransport(base_url=url, cluster=cluster, token=token)


_TRANSPORTS: dict[str, Any] = {
    "http": _http_factory,
    "posthog_proxy": _posthog_proxy_factory,
}
