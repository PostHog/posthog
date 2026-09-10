"""Shallow, repeatable liveness probe for registry servers.

Deliberately less thorough than mcp_store's activation probe: that one performs a
real RFC 7591 DCR registration, which mints an OAuth client on the vendor's system
and therefore can only run once per server. This probe is side-effect-free (one
`initialize` handshake to classify liveness + auth, plus `tools/list` when the
server answers without credentials), so it can sweep the whole index on a schedule
and keep liveness a living signal.
"""

import json
from dataclasses import field
from typing import Any

from django.utils import timezone

import requests
import structlog

from posthog.dataclasses import frozen
from posthog.security.pinned_requests import SSRFBlockedError, pinned_request

from products.mcp_registry.backend.constants import (
    PROBE_BATCH_SIZE,
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


def _classify_auth(response: requests.Response) -> str:
    www_authenticate = response.headers.get("WWW-Authenticate", "")
    if "bearer" in www_authenticate.lower():
        return "oauth"
    hint = (www_authenticate + response.text[:400]).lower()
    if "api key" in hint or "api-key" in hint or "api_key" in hint:
        return "api_key"
    return "unknown"


def _rpc(url: str, payload: dict[str, Any], session_id: str | None = None) -> requests.Response:
    headers = dict(_HEADERS)
    if session_id:
        headers["mcp-session-id"] = session_id
    return pinned_request("POST", url, json=payload, headers=headers, timeout=PROBE_TIMEOUT_SECONDS)


def _fetch_tools(url: str, session_id: str | None) -> list[dict[str, Any]]:
    _rpc(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id)
    response = _rpc(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, session_id)
    body = _parse_jsonrpc_body(response.text) or {}
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
        return ProbeOutcome(liveness="alive_auth", auth_method=_classify_auth(response))
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


def probe_stalest_servers(batch_size: int = PROBE_BATCH_SIZE) -> int:
    """Probe the servers with the oldest (or missing) probe results. Returns count probed.

    Measured servers first, because their liveness backs real rankings, then the long tail,
    so the whole index converges over successive scheduled runs.
    """
    queryset = (
        MCPRegistryServer.objects.exclude(canonical_url="")
        .order_by("-is_measured", "last_probed_at")
        .values_list("id", flat=True)[:batch_size]
    )
    probed = 0
    for server_id in list(queryset):
        server = MCPRegistryServer.objects.get(pk=server_id)
        apply_probe_outcome(server, shallow_probe(server.canonical_url))
        probed += 1
    logger.info("mcp_registry.probe.batch_done", probed=probed)
    return probed
