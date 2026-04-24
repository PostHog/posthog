"""ClickHouse transport for autoresearch campaigns.

One transport: :class:`PosthogProxyTransport`. Routes queries through
PostHog's OAuth-gated proxy (``/api/query_performance_proxy/execute-test/``),
which fronts ClickHouse through the locked-down ``autoresearch`` CH user.

We deliberately don't expose a direct-to-CH HTTP transport: without it,
there's only one wire format, one safety posture, and one authn path —
the proxy — so the comparison oracle doesn't need to reconcile cross-
transport differences, and every campaign query is observable in the
PostHog logs.
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

_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


def _require_http_url(url: str) -> None:
    """Reject non-HTTP(S) URLs before we hand them to urllib.

    ``urllib.request`` speaks ``file://``, ``ftp://``, and other schemes.
    A malicious or misconfigured ``adapter.json`` / env var could abuse
    those to read local files or reach unexpected services. The transports
    only ever need HTTP(S), so refuse anything else.
    """
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in _ALLOWED_URL_SCHEMES:
        raise ValueError(f"transport URL scheme {scheme!r} not allowed (must be http/https): {url!r}")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse all 3XX redirects.

    Every endpoint these transports talk to is a PostHog API or a known
    ClickHouse HTTP listener — none of them should ever redirect a legitimate
    request. If a redirect happens it's a sign of misconfiguration or
    attempted SSRF (e.g. a 302 to ``file:///etc/passwd`` after the initial
    scheme check). `_require_http_url` only validates the caller-supplied URL;
    this handler seals the redirect-based bypass.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise urllib.error.HTTPError(req.full_url, code, f"refusing to follow redirect to {newurl!r}", headers, fp)


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler())


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


class TransportError(RuntimeError):
    """Raised when a transport fails to run a query."""

    def __init__(self, message: str, *, elapsed_ms: float, stdout: str):
        super().__init__(message)
        self.elapsed_ms = elapsed_ms
        self.stdout = stdout


def load_transport(config: dict[str, Any]) -> Transport:
    """Build a :class:`Transport` from a parsed ``adapter.json`` config."""
    kind = config.get("type")
    if not kind:
        raise ValueError('adapter.json must set a "type" field')
    factory = _TRANSPORTS.get(kind)
    if factory is None:
        raise ValueError(f"unknown adapter type: {kind!r} (supported: {sorted(_TRANSPORTS)})")
    return factory(config)


class PosthogProxyTransport(Transport):
    """Routes queries through PostHog's OAuth-gated ClickHouse proxy.

    Config shape::

        {
          "type": "posthog_proxy",
          "url": "https://posthog.example.com",   # base URL of the PostHog app
          "token": "<oauth access token>"         # must have clickhouse_test_cluster_perf:test_read scope
        }

    The proxy enforces ``readonly = 2`` server-side, so this transport stays
    a thin shim: POST JSON, unwrap the response payload into a
    :class:`TransportResult`.
    """

    def __init__(self, *, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    # Server-side CH cap is 300s (MAX_EXECUTION_TIME_SECONDS in the proxy).
    # Clamp the client-side timeout a touch above that so we always see a
    # concrete CH error instead of a socket read timeout; reject anything
    # that tries to invert the ordering (would produce "transport failure"
    # with no server-side metrics and poison the campaign comparison).
    _MAX_TIMEOUT_S = 360

    def run(self, sql: str, *, timeout_s: int = 310) -> TransportResult:
        if timeout_s > self._MAX_TIMEOUT_S:
            # TransportError (not ValueError) so the caller's existing
            # `except TransportError` path routes this into the orderly
            # failure-metrics flow instead of crashing the campaign.
            raise TransportError(
                f"posthog_proxy timeout_s={timeout_s} exceeds max {self._MAX_TIMEOUT_S}; "
                "the server caps queries at 300s — clamp the caller.",
                elapsed_ms=0.0,
                stdout="",
            )
        endpoint = f"{self.base_url}/api/query_performance_proxy/execute-test/"
        _require_http_url(endpoint)
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
            # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            with _NO_REDIRECT_OPENER.open(req, timeout=timeout_s) as resp:  # noqa: S310
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
            # Proxy returns rows as a native JSON list; serialize each row as
            # a JSON line for on-disk diffing. The compare-results script
            # sorts lines before comparison, so line order off the wire
            # doesn't matter. JSON is round-trip safe for nulls / tabs /
            # newlines embedded in values — TSV would need escaping.
            result_bytes=_rows_to_jsonl_bytes(data.get("result")),
            elapsed_ms=float(elapsed_ms),
            rows_read=data.get("rows_read") if isinstance(data.get("rows_read"), int) else None,
            bytes_read=data.get("bytes_read") if isinstance(data.get("bytes_read"), int) else None,
            stdout=f"query_id={data.get('query_id')}",
        )


def _rows_to_jsonl_bytes(rows: Any) -> bytes:
    """Serialize a list of rows as newline-delimited JSON, bytes-encoded.

    Each row becomes one JSON-encoded line. Empty result → empty bytes.
    Non-list input (defensive — the proxy shouldn't send this) → empty.
    """
    if not isinstance(rows, list) or not rows:
        return b""
    lines = [json.dumps(row, separators=(",", ":"), sort_keys=True) for row in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _posthog_proxy_factory(config: dict[str, Any]) -> Transport:
    url = config.get("url")
    token = config.get("token")
    if not url:
        raise ValueError('adapter type "posthog_proxy" requires a "url" field')
    if not token:
        raise ValueError('adapter type "posthog_proxy" requires a "token" field')
    return PosthogProxyTransport(base_url=url, token=token)


_TRANSPORTS: dict[str, Any] = {
    "posthog_proxy": _posthog_proxy_factory,
}
