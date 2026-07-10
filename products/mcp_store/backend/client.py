"""Sync upstream MCP client for ``tools/call``.

Extends the streamable-HTTP handshake used by ``tools.py`` for ``tools/list``:
``initialize`` → ``notifications/initialized`` → ``tools/call`` → ``DELETE``.
A fresh handshake per call keeps the client stateless — upstream sessions are
short-lived and terminated best-effort after each call.
"""

import json
from typing import Any

import httpx
import structlog

from posthog.security.url_validation import is_url_allowed

from .models import MCPServerInstallation
from .proxy import (
    MAX_PROXY_BODY_SIZE,
    UPSTREAM_TIMEOUT,
    build_upstream_auth_headers,
    validated_same_origin_redirect_url,
)
from .tools import (
    HANDSHAKE_TIMEOUT,
    ToolsFetchError,
    _mcp_initialize,
    _mcp_send_initialized,
    _mcp_terminate_session,
    _parse_jsonrpc_response,
)

logger = structlog.get_logger(__name__)

_CALL_TOOL_ID = 3


class UpstreamToolCallError(Exception):
    """Raised when the upstream MCP server can't be called or returns a JSON-RPC error.

    ``error_type`` is a stable machine-readable category surfaced in REST 502
    responses and ``$mcp_error_type`` analytics.
    """

    def __init__(self, message: str, *, error_type: str = "upstream_error") -> None:
        super().__init__(message)
        self.error_type = error_type


def call_upstream_tool(
    installation: MCPServerInstallation, tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Execute a single ``tools/call`` against the installation's MCP server.

    Returns the raw JSON-RPC ``result`` (MCP ``CallToolResult``: ``content``,
    ``isError``, optional ``structuredContent``). Approval enforcement and token
    refresh are the caller's responsibility (see ``gateway.py``).
    """
    allowed, reason = is_url_allowed(installation.url)
    if not allowed:
        raise UpstreamToolCallError(f"URL not allowed: {reason}", error_type="ssrf_blocked")

    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": _CALL_TOOL_ID,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
    ).encode()
    if len(body) > MAX_PROXY_BODY_SIZE:
        raise UpstreamToolCallError("Tool arguments too large", error_type="payload_too_large")

    auth_headers = build_upstream_auth_headers(installation)
    base_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **auth_headers,
    }

    try:
        with httpx.Client(timeout=HANDSHAKE_TIMEOUT) as client:
            session_id, upstream_url = _mcp_initialize(client, installation.url, base_headers)
            session_headers = dict(base_headers)
            if session_id:
                session_headers["Mcp-Session-Id"] = session_id

            _mcp_send_initialized(client, upstream_url, session_headers)
            try:
                return _send_tool_call(client, upstream_url, body, session_headers)
            finally:
                # Best-effort session cleanup; failures here must not mask the call result.
                if session_id:
                    _mcp_terminate_session(client, upstream_url, session_headers)
    except UpstreamToolCallError:
        raise
    except ToolsFetchError as exc:
        raise UpstreamToolCallError(str(exc)) from exc
    except httpx.ConnectError as exc:
        raise UpstreamToolCallError("Upstream MCP server unreachable", error_type="unreachable") from exc
    except httpx.TimeoutException as exc:
        raise UpstreamToolCallError("Upstream MCP server timed out", error_type="timeout") from exc


def _send_tool_call(client: httpx.Client, url: str, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
    # Tool execution can be slow (matches the proxy's budget); the handshake
    # steps keep the aggressive HANDSHAKE_TIMEOUT set on the client.
    response = client.post(url, content=body, headers=headers, timeout=UPSTREAM_TIMEOUT)
    redirect_url = validated_same_origin_redirect_url(url, response)
    if redirect_url:
        response.close()
        response = client.post(redirect_url, content=body, headers=headers, timeout=UPSTREAM_TIMEOUT)
        url = redirect_url

    if response.status_code >= 400:
        logger.warning(
            "Upstream tools/call returned error status",
            url=url,
            status_code=response.status_code,
        )
        raise UpstreamToolCallError(f"Upstream returned status {response.status_code}")

    payload = _parse_jsonrpc_response(
        response.text, response.headers.get("content-type", ""), _CALL_TOOL_ID, request_name="tools/call"
    )
    if isinstance(payload, dict) and payload.get("error"):
        error = payload["error"]
        message = (
            error.get("message", "Upstream tools/call returned an error") if isinstance(error, dict) else str(error)
        )
        raise UpstreamToolCallError(message)

    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        raise UpstreamToolCallError("tools/call response missing 'result' object")
    return result
