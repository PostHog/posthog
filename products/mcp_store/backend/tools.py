"""Helpers for fetching and caching the tools an upstream MCP server exposes.

The proxy enforces per-tool approval (`approved` / `needs_approval` / `do_not_use`)
against these cached rows — so they need to stay reasonably fresh. Refresh happens
on successful install/reconnect and on-demand via the UI's "Refresh tools" button.
"""

import json
from typing import Any

from django.utils import timezone

import httpx
import structlog

from posthog.security.url_validation import is_url_allowed

from .models import MCPServerInstallation, MCPServerInstallationTool
from .oauth import TokenRefreshError, is_token_expiring, refresh_installation_token
from .policy import SYNC_DEFAULT_APPROVAL_STATE
from .proxy import build_upstream_auth_headers, validated_same_origin_redirect_url

logger = structlog.get_logger(__name__)

# JSON-RPC ids for each step of the handshake. Values are arbitrary, but we
# pick stable ones so response matching in _parse_jsonrpc_response is trivial.
_INITIALIZE_ID = 1
_TOOLS_LIST_ID = 2
_TOOLS_CALL_ID = 3

# MCP protocol version we claim to speak. Kept in sync with what the PostHog
# MCP reference client sends; bump when the spec changes in a backwards-
# incompatible way.
_PROTOCOL_VERSION = "2024-11-05"
_CLIENT_INFO: dict[str, Any] = {"name": "posthog-mcp-store", "version": "1.0"}

# Each handshake step should return in well under a second.
# We cap it aggressively (separate from the proxy's 180s, which
# covers real tool execution) so a hung upstream can't pin a Django worker.
HANDSHAKE_TIMEOUT = 10

# A real tool call does actual work upstream, so it needs more room than the
# discovery handshake. Still well under the proxy's 180s: this path serves an
# interactive agent, and a worker blocked for minutes is worse than a retry.
CALL_TIMEOUT = 60


class ToolsFetchError(Exception):
    pass


class ToolCallError(Exception):
    """An upstream ``tools/call`` failed. Distinct from ToolsFetchError so
    callers can tell "we couldn't discover tools" from "the call itself
    failed" — they surface differently to an agent."""


def _ensure_valid_token_for_fetch(installation: MCPServerInstallation) -> None:
    if installation.auth_type != "oauth":
        return
    sensitive = installation.sensitive_configuration or {}
    if not is_token_expiring(sensitive):
        return
    try:
        refresh_installation_token(installation)
    except TokenRefreshError as exc:
        raise ToolsFetchError(f"Token refresh failed: {exc}") from exc


def fetch_upstream_tools(installation: MCPServerInstallation) -> list[dict[str, Any]]:
    """Send a JSON-RPC ``tools/list`` to the upstream MCP server and return its tool array.

    Follows the MCP streamable HTTP handshake: ``initialize`` → ``notifications/initialized``
    → ``tools/list`` → ``DELETE`` (to terminate the short-lived session). Most MCP
    servers reject ``tools/list`` without a valid ``Mcp-Session-Id``, which we only
    receive as a response header on ``initialize``.

    Shares the proxy's SSRF guard + timeout + auth-header builder so behavior stays
    consistent between proxy traffic and sync traffic.
    """
    allowed, reason = is_url_allowed(installation.url)
    if not allowed:
        raise ToolsFetchError(f"URL not allowed: {reason}")

    _ensure_valid_token_for_fetch(installation)

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
                return _mcp_list_tools(client, upstream_url, session_headers)
            finally:
                # Best-effort cleanup so we don't leak sessions upstream. Failures
                # here are purely janitorial and must not mask real errors above.
                if session_id:
                    _mcp_terminate_session(client, upstream_url, session_headers)
    except httpx.ConnectError as exc:
        raise ToolsFetchError("Upstream MCP server unreachable") from exc
    except httpx.TimeoutException as exc:
        raise ToolsFetchError("Upstream MCP server timed out") from exc


def call_upstream_tool(
    installation: MCPServerInstallation,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Invoke one tool on the upstream MCP server and return its ``result`` object.

    Same short-lived handshake as :func:`fetch_upstream_tools` — servers hand out a
    session on ``initialize`` and most reject ``tools/call`` without it — so the two
    paths share the SSRF guard, auth headers and redirect handling.

    Approval and audit are *not* handled here: the caller runs the request through
    the gateway's policy engine first (see ``enforce_tool_approval``), so this stays
    a transport concern.
    """
    allowed, reason = is_url_allowed(installation.url)
    if not allowed:
        raise ToolCallError(f"URL not allowed: {reason}")

    _ensure_valid_token_for_fetch(installation)

    auth_headers = build_upstream_auth_headers(installation)
    base_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **auth_headers,
    }

    try:
        with httpx.Client(timeout=CALL_TIMEOUT) as client:
            session_id, upstream_url = _mcp_initialize(client, installation.url, base_headers)
            session_headers = dict(base_headers)
            if session_id:
                session_headers["Mcp-Session-Id"] = session_id

            _mcp_send_initialized(client, upstream_url, session_headers)
            try:
                return _mcp_call_tool(client, upstream_url, session_headers, tool_name, arguments)
            finally:
                if session_id:
                    _mcp_terminate_session(client, upstream_url, session_headers)
    except httpx.ConnectError as exc:
        raise ToolCallError("Upstream MCP server unreachable") from exc
    except httpx.TimeoutException as exc:
        raise ToolCallError("Upstream MCP server timed out") from exc


def _post_with_same_origin_redirect(
    client: httpx.Client,
    url: str,
    *,
    content: bytes,
    headers: dict[str, str],
) -> tuple[httpx.Response, str]:
    response = client.post(url, content=content, headers=headers)
    redirect_url = validated_same_origin_redirect_url(url, response)
    if not redirect_url:
        return response, url

    response.close()
    return client.post(redirect_url, content=content, headers=headers), redirect_url


def _mcp_initialize(client: httpx.Client, url: str, headers: dict[str, str]) -> tuple[str | None, str]:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": _INITIALIZE_ID,
            "method": "initialize",
            "params": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": _CLIENT_INFO,
            },
        }
    ).encode()

    response, upstream_url = _post_with_same_origin_redirect(client, url, content=body, headers=headers)
    if response.status_code >= 400:
        logger.warning(
            "initialize request returned error",
            url=upstream_url,
            status_code=response.status_code,
            body=response.text[:500],
        )
        raise ToolsFetchError(f"Upstream initialize returned status {response.status_code}")

    payload = _parse_jsonrpc_response(
        response.text, response.headers.get("content-type", ""), _INITIALIZE_ID, request_name="initialize"
    )
    if isinstance(payload, dict) and payload.get("error"):
        raise ToolsFetchError(f"Upstream initialize returned error: {payload['error']}")

    # Session id is optional per the spec — servers that don't need one still
    # work with tools/list, so treat a missing header as "no session needed".
    return response.headers.get("mcp-session-id"), upstream_url


def _mcp_send_initialized(client: httpx.Client, url: str, headers: dict[str, str]) -> None:
    """Send the ``notifications/initialized`` notification after ``initialize``.

    This is a JSON-RPC notification (no id, no response expected). Servers
    typically return 202 Accepted. Failures are logged and swallowed because
    some servers skip this step entirely.
    """
    body = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}).encode()
    try:
        response, _upstream_url = _post_with_same_origin_redirect(client, url, content=body, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("notifications/initialized transport failed; continuing", url=url, error=str(exc))
        return
    if response.status_code >= 400:
        logger.warning(
            "notifications/initialized returned error; continuing",
            url=url,
            status_code=response.status_code,
            body=response.text[:500],
        )


def _mcp_list_tools(client: httpx.Client, url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    body = json.dumps({"jsonrpc": "2.0", "id": _TOOLS_LIST_ID, "method": "tools/list", "params": {}}).encode()

    response, upstream_url = _post_with_same_origin_redirect(client, url, content=body, headers=headers)
    if response.status_code >= 400:
        logger.warning(
            "tools/list request returned error",
            url=upstream_url,
            status_code=response.status_code,
            body=response.text[:500],
        )
        raise ToolsFetchError(f"Upstream returned status {response.status_code}")

    payload = _parse_jsonrpc_response(
        response.text, response.headers.get("content-type", ""), _TOOLS_LIST_ID, request_name="tools/list"
    )
    if isinstance(payload, dict) and payload.get("error"):
        raise ToolsFetchError(f"Upstream tools/list returned error: {payload['error']}")

    result = (payload or {}).get("result") if isinstance(payload, dict) else None
    tools = (result or {}).get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list):
        raise ToolsFetchError("tools/list response missing 'result.tools' array")

    return [t for t in tools if isinstance(t, dict) and t.get("name")]


def _mcp_call_tool(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": _TOOLS_CALL_ID,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
    ).encode()

    response, upstream_url = _post_with_same_origin_redirect(client, url, content=body, headers=headers)
    if response.status_code >= 400:
        logger.warning(
            "tools/call request returned error",
            url=upstream_url,
            tool_name=tool_name,
            status_code=response.status_code,
            body=response.text[:500],
        )
        raise ToolCallError(f"Upstream returned status {response.status_code}")

    payload = _parse_jsonrpc_response(
        response.text,
        response.headers.get("content-type", ""),
        _TOOLS_CALL_ID,
        request_name="tools/call",
        error_class=ToolCallError,
    )
    if isinstance(payload, dict) and payload.get("error"):
        raise ToolCallError(f"Upstream tools/call returned error: {payload['error']}")

    result = (payload or {}).get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        raise ToolCallError("tools/call response missing 'result' object")

    # A result with `isError` set is the tool telling the *model* it failed (bad
    # arguments, not-found, ...), not a transport fault. Pass it through so the
    # agent can correct itself instead of seeing an opaque gateway error.
    return result


def _mcp_terminate_session(client: httpx.Client, url: str, headers: dict[str, str]) -> None:
    try:
        client.delete(url, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("session DELETE failed; ignoring", url=url, error=str(exc))


def _parse_jsonrpc_response(
    body: str,
    content_type: str,
    expected_id: int,
    *,
    request_name: str,
    error_class: type[Exception] = ToolsFetchError,
) -> dict[str, Any]:
    """Parse a JSON-RPC response body that may be plain JSON or SSE-wrapped.

    MCP streamable HTTP servers can reply either directly with JSON or over an
    ``text/event-stream`` frame (``data:`` line carrying the JSON-RPC payload).
    We pick the parser based on ``content-type`` but fall back to sniffing the
    body because some proxies mislabel the stream.
    """
    content_type_lower = (content_type or "").lower()
    stripped = body.lstrip()
    if "text/event-stream" in content_type_lower or stripped.startswith(("event:", "data:", ":")):
        for block in body.split("\n\n"):
            for line in block.splitlines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if not data:
                    continue
                try:
                    parsed = json.loads(data)
                except ValueError:
                    continue
                if isinstance(parsed, dict) and parsed.get("id") == expected_id:
                    return parsed
        raise error_class(
            f"Upstream {request_name} SSE response did not contain a JSON-RPC message with id={expected_id}"
        )
    try:
        return json.loads(body)
    except ValueError as exc:
        raise error_class(
            f"Upstream {request_name} response was not JSON "
            f"(content-type={content_type_lower!r}, body_preview={body[:200]!r})"
        ) from exc


def sync_installation_tools(installation: MCPServerInstallation) -> list[MCPServerInstallationTool]:
    """Upsert tool rows for an installation against the latest upstream ``tools/list``.

    - New tools are inserted with ``approval_state="needs_approval"`` (explicit opt-in).
    - Existing tools keep their approval state; name/description/schema/annotations/last_seen_at are updated.
    - Tools that disappear upstream get ``removed_at`` set (approval state preserved for later).
    - Tools that reappear get ``removed_at`` cleared.
    """
    upstream_tools = fetch_upstream_tools(installation)
    now = timezone.now()

    existing_by_name = {t.tool_name: t for t in installation.tools.all()}
    seen_names: set[str] = set()

    for tool in upstream_tools:
        tool_name = tool["name"]
        seen_names.add(tool_name)
        display_name = tool.get("title") or tool.get("displayName") or ""
        description = tool.get("description") or ""
        input_schema = tool.get("inputSchema") or {}
        annotations = tool.get("annotations") or {}

        row = existing_by_name.get(tool_name)
        if row is None:
            MCPServerInstallationTool.objects.create(
                installation=installation,
                tool_name=tool_name,
                display_name=display_name,
                description=description,
                input_schema=input_schema,
                annotations=annotations,
                # New tools default to needs_approval so adoption stays explicit.
                # The policy engine keys off this exact value to tell a synced
                # default apart from a member's real choice — keep them in step.
                approval_state=SYNC_DEFAULT_APPROVAL_STATE,
                last_seen_at=now,
                removed_at=None,
            )
        else:
            row.display_name = display_name
            row.description = description
            row.input_schema = input_schema
            row.annotations = annotations
            row.last_seen_at = now
            # A previously-removed tool reappeared; preserve approval_state but clear the flag.
            row.removed_at = None
            row.save(
                update_fields=[
                    "display_name",
                    "description",
                    "input_schema",
                    "annotations",
                    "last_seen_at",
                    "removed_at",
                    "updated_at",
                ]
            )

    # Mark anything we didn't see as removed; keep their approval_state intact.
    for tool_name, row in existing_by_name.items():
        if tool_name in seen_names:
            continue
        if row.removed_at is not None:
            continue
        row.removed_at = now
        row.save(update_fields=["removed_at", "updated_at"])

    return list(installation.tools.all())
