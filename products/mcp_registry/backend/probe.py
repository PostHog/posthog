"""Shallow, repeatable liveness probe for registry servers.

Deliberately less thorough than mcp_store's activation probe: that one performs a
real RFC 7591 DCR registration, which mints an OAuth client on the vendor's system
and therefore can only run once per server. This probe is side-effect-free (one
`initialize` handshake to classify liveness + auth, plus `tools/list` when the
server answers without credentials), so it can sweep the whole index on a schedule
and keep liveness a living signal.
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import field
from typing import Any

from django.db.models import F
from django.utils import timezone

import requests
import structlog

from posthog.dataclasses import frozen
from posthog.security.pinned_requests import SSRFBlockedError, pinned_session

from products.mcp_registry.backend.constants import (
    PROBE_BATCH_SIZE,
    PROBE_CONCURRENCY,
    PROBE_RESPONSE_MAX_BYTES,
    PROBE_TIMEOUT_SECONDS,
    PROBE_TOOL_DESCRIPTION_MAX_CHARS,
    PROBE_TOOL_LIMIT,
)
from products.mcp_registry.backend.models import MCPRegistryServer, MCPRegistryTool

logger = structlog.get_logger(__name__)

_PROTOCOL_VERSION = "2025-06-18"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
_INITIALIZE_PAYLOAD = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": _PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "posthog-mcp-registry-probe", "version": "0.1"},
    },
}


@frozen
class ProbeOutcome:
    liveness: str = "dead"  # a LIVENESS_CHOICES key
    auth_method: str = "unknown"  # an AUTH_METHOD_CHOICES key
    detail: str = ""
    tools: list[dict[str, Any]] = field(default_factory=list)


def _parse_jsonrpc_body(text: str) -> dict[str, Any] | None:
    """Streamable-HTTP responses arrive as raw JSON or as an SSE frame."""
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except ValueError:
            return None
    for line in stripped.splitlines():
        if line.startswith("data:"):
            try:
                return json.loads(line[len("data:") :].strip())
            except ValueError:
                continue
    return None


def _classify_auth(headers: Any, text: str) -> str:
    www_authenticate = headers.get("WWW-Authenticate", "")
    if "bearer" in www_authenticate.lower():
        return "oauth"
    hint = (www_authenticate + text[:400]).lower()
    if "api key" in hint or "api-key" in hint or "api_key" in hint:
        return "api_key"
    return "unknown"


@frozen
class _RpcResponse:
    """A probe response with the body already read and bounded.

    The body is never more than PROBE_RESPONSE_MAX_BYTES, so callers can parse it without
    a publisher-controlled endpoint deciding how much memory the worker holds.
    """

    status_code: int
    headers: Any
    text: str
    truncated: bool = False


def _read_bounded(response: requests.Response, limit: int = PROBE_RESPONSE_MAX_BYTES) -> tuple[str, bool]:
    """Read a streamed response body, stopping at ``limit`` bytes.

    ``requests`` would otherwise buffer the entire body in memory; with PROBE_CONCURRENCY
    probes in flight, a few oversized publisher endpoints could OOM the worker. Iterating
    the stream caps what we hold regardless of how much the server sends. Returns the
    decoded text (best-effort) and whether it was cut short.
    """
    chunks: list[bytes] = []
    received = 0
    truncated = False
    for chunk in response.iter_content(chunk_size=65536):
        received += len(chunk)
        if received > limit:
            chunks.append(chunk[: max(0, len(chunk) - (received - limit))])
            truncated = True
            break
        chunks.append(chunk)
    body = b"".join(chunks)
    encoding = response.encoding or "utf-8"
    return body.decode(encoding, errors="replace"), truncated


def _rpc(url: str, payload: dict[str, Any], session_id: str | None = None) -> _RpcResponse:
    headers = dict(_HEADERS)
    if session_id:
        headers["mcp-session-id"] = session_id
    # Stream so the body is read under PROBE_RESPONSE_MAX_BYTES rather than buffered whole.
    # The session must stay open while we read, so this uses pinned_session directly.
    with pinned_session(url) as session:
        response = session.post(
            url, json=payload, headers=headers, timeout=PROBE_TIMEOUT_SECONDS, stream=True, allow_redirects=False
        )
        try:
            text, truncated = _read_bounded(response)
            return _RpcResponse(
                status_code=response.status_code, headers=response.headers, text=text, truncated=truncated
            )
        finally:
            response.close()


def _fetch_tools(url: str, session_id: str | None) -> list[dict[str, Any]]:
    _rpc(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id)
    response = _rpc(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, session_id)
    body = {} if response.truncated else (_parse_jsonrpc_body(response.text) or {})
    tools = (body.get("result") or {}).get("tools")
    if not isinstance(tools, list):
        return []
    return [
        {
            "name": tool.get("name") or "",
            "description": (tool.get("description") or "")[:PROBE_TOOL_DESCRIPTION_MAX_CHARS],
            "input_schema": tool.get("inputSchema") or {},
        }
        for tool in tools[:PROBE_TOOL_LIMIT]
        if tool.get("name")
    ]


def shallow_probe(url: str) -> ProbeOutcome:
    """Classify one server URL. Never raises."""
    try:
        response = _rpc(url, _INITIALIZE_PAYLOAD)
    except SSRFBlockedError as exc:
        return ProbeOutcome(detail=f"ssrf_blocked: {exc}"[:200])
    except requests.RequestException as exc:
        return ProbeOutcome(detail=str(exc)[:200])

    if 300 <= response.status_code < 400:
        # A redirect target never went through SSRF validation, so refuse to follow.
        return ProbeOutcome(liveness="not_mcp", detail=f"redirect http {response.status_code}")

    if response.truncated:
        # The body blew past the read cap, so it isn't a usable JSON-RPC envelope.
        return ProbeOutcome(liveness="not_mcp", detail=f"response exceeded {PROBE_RESPONSE_MAX_BYTES} bytes")

    body = _parse_jsonrpc_body(response.text)
    result = (body or {}).get("result") or {}
    if result.get("serverInfo") or result.get("capabilities"):
        tools: list[dict[str, Any]] = []
        detail = ""
        try:
            tools = _fetch_tools(url, response.headers.get("mcp-session-id"))
        except (requests.RequestException, SSRFBlockedError) as exc:
            detail = f"tools/list failed: {exc}"[:200]
        return ProbeOutcome(liveness="alive_open", auth_method="none", detail=detail, tools=tools)

    if response.status_code in (401, 403):
        return ProbeOutcome(liveness="alive_auth", auth_method=_classify_auth(response.headers, response.text))
    if response.status_code == 200 and (body or {}).get("error"):
        return ProbeOutcome(liveness="alive_protocol", detail=f"rpc error {(body or {})['error'].get('code')}")
    if 200 <= response.status_code < 300:
        return ProbeOutcome(liveness="not_mcp", detail=f"http {response.status_code}")
    return ProbeOutcome(detail=f"http {response.status_code}")


def apply_probe_outcome(server: MCPRegistryServer, outcome: ProbeOutcome) -> None:
    server.liveness = outcome.liveness
    if outcome.auth_method != "unknown" or server.auth_method == "unknown":
        server.auth_method = outcome.auth_method
    server.probe_detail = outcome.detail
    server.last_probed_at = timezone.now()
    server.save(update_fields=["liveness", "auth_method", "probe_detail", "last_probed_at", "updated_at"])

    seen_at = server.last_probed_at
    for tool in outcome.tools:
        MCPRegistryTool.objects.update_or_create(
            server=server,
            name=tool["name"],
            defaults={
                "description": tool["description"],
                "input_schema": tool["input_schema"],
                "source": "tools_list",
                "last_seen_at": seen_at,
            },
        )


def probeable_server_count() -> int:
    """How many servers the probe can reach at all. Package-only entries have no URL."""
    return MCPRegistryServer.objects.exclude(canonical_url="").count()


def probe_stalest_servers(batch_size: int = PROBE_BATCH_SIZE, concurrency: int = PROBE_CONCURRENCY) -> int:
    """Probe the servers with the oldest (or missing) probe results. Returns count probed.

    Measured servers first, because their liveness backs real rankings, then the long tail,
    so the whole index converges over successive scheduled runs.

    Each probe waits on a remote server for up to PROBE_TIMEOUT_SECONDS, so the batch runs
    concurrently: serially, a sweep of the whole index would take days and liveness would
    stay stale enough to distort ranking. Only the HTTP call is threaded. Django opens a
    connection per thread, so the row writes stay on this thread instead of leaving a
    connection per worker behind.
    """
    servers = list(
        MCPRegistryServer.objects.exclude(canonical_url="")
        # nulls_first, or the sweep never converges: Postgres sorts NULL last on an
        # ascending column, so never-probed servers would queue behind every server that
        # already has a timestamp, and each run would re-probe the same batch forever.
        .order_by("-is_measured", F("last_probed_at").asc(nulls_first=True))
        .only("id", "canonical_url", "auth_method")[:batch_size]
    )
    if not servers:
        return 0

    probed = 0
    with ThreadPoolExecutor(max_workers=min(concurrency, len(servers))) as pool:
        pending = {pool.submit(shallow_probe, server.canonical_url): server for server in servers}
        for future in as_completed(pending):
            server = pending[future]
            try:
                outcome = future.result()
            except Exception:
                # One pathological server must not abandon the rest of the sweep.
                logger.exception("mcp_registry.probe.server_failed", server_id=str(server.id))
                continue
            apply_probe_outcome(server, outcome)
            probed += 1
    logger.info("mcp_registry.probe.batch_done", probed=probed, selected=len(servers))
    return probed
