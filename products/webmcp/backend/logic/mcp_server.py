from typing import Any

from django.conf import settings

import requests

from posthog.models import User

from ..facade.contracts import ExecResult, ExecTool, McpServerError
from .tokens import WebMCPTokenIssuer

# The stateless MCP dialect needs no handshake, so each proxied call is one HTTP request.
PROTOCOL_VERSION = "2026-07-28"
CLIENT_INFO = {"name": "posthog-webmcp", "version": "1.0.0"}
EXEC_TOOL_NAME = "exec"
# Connect, read. The read timeout covers slow tools such as SQL queries.
REQUEST_TIMEOUT_SECONDS = (5, 120)


def get_mcp_server_url() -> str | None:
    """The MCP server URL that WebMCP can send user tokens to, or None when WebMCP is not available."""
    url = settings.MCP_SERVER_URL
    # Every request carries a bearer token for the user, so plain HTTP is for a local MCP server only.
    if not url or (not url.startswith("https://") and not settings.DEBUG):
        return None
    return url


class McpServerClient:
    """Talks to the PostHog MCP server in single-`exec` mode, for one user and team.

    The views that call this client are sync, so each call holds a web worker until the MCP server
    answers, which can take up to the read timeout. The MCP server runs the tool by calling this
    API with the minted token, so a slow call holds a second worker for the same time.

    An async view would release the worker while it waits.
    The larger step is for the browser to call the MCP server directly, which removes this proxy.
    That is not simple, for these reasons:
    - The MCP server accepts only bearer tokens. The session cookie belongs to the app origin, so
      the browser does not send it to the MCP host.
    - The browser must then hold an access token. Page scripts can read that token, so an XSS
      gets a token that works outside the session. Here, the token never leaves the server.
    - The MCP server must allow CORS from every app origin, and each region has its own MCP host.
    """

    def __init__(self, *, url: str, token: str) -> None:
        self._url = url
        self._token = token

    @classmethod
    def for_user(cls, user: User, team_id: int) -> "McpServerClient":
        url = get_mcp_server_url()
        if url is None:
            raise McpServerError("WebMCP is not available on this instance")
        return cls(url=url, token=WebMCPTokenIssuer.for_instance().get_or_mint(user, team_id))

    def get_exec_tool(self) -> ExecTool:
        result = self._request("tools/list", {})
        for tool in result.get("tools", []):
            if isinstance(tool, dict) and tool.get("name") == EXEC_TOOL_NAME:
                return ExecTool(
                    name=EXEC_TOOL_NAME,
                    description=tool.get("description") or "",
                    input_schema=tool.get("inputSchema") or {"type": "object"},
                )
        raise McpServerError("The MCP server did not advertise the exec tool")

    def call_exec(self, command: str) -> ExecResult:
        result = self._request(
            "tools/call", {"name": EXEC_TOOL_NAME, "arguments": {"command": command}}, name=EXEC_TOOL_NAME
        )
        content = result.get("content")
        return ExecResult(
            content=[block for block in content if isinstance(block, dict)] if isinstance(content, list) else [],
            is_error=result.get("isError") is True,
        )

    def _request(self, method: str, params: dict[str, Any], *, name: str | None = None) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Mcp-Method": method,
            # CLI mode makes the MCP server advertise only the single `exec` tool, which WebMCP registers as its one tool.
            "x-posthog-mcp-mode": "cli",
            "x-posthog-mcp-consumer": "webmcp",
        }
        if name is not None:
            headers["Mcp-Name"] = name
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": {
                **params,
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                    "io.modelcontextprotocol/clientInfo": CLIENT_INFO,
                    "io.modelcontextprotocol/clientCapabilities": {},
                },
            },
        }
        try:
            # A redirect can resend the bearer token and the command to a URL nobody configured.
            response = requests.post(
                self._url, json=body, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False
            )
        except requests.RequestException as error:
            raise McpServerError(f"Could not reach the MCP server: {error.__class__.__name__}") from error

        if 300 <= response.status_code < 400:
            raise McpServerError(f"The MCP server returned HTTP {response.status_code}")
        # Revoking the app deletes its tokens, so get_or_mint never reuses a revoked token and a retry with a
        # new token cannot fix a 401.
        if response.status_code == 401:
            raise McpServerError("The MCP server rejected the access token")
        try:
            payload = response.json()
        except ValueError as error:
            raise McpServerError(f"The MCP server returned HTTP {response.status_code}") from error
        if not isinstance(payload, dict):
            raise McpServerError("The MCP server returned an unexpected response")
        if error_body := payload.get("error"):
            message = error_body.get("message") if isinstance(error_body, dict) else None
            raise McpServerError(message or "The MCP server returned an error")
        if not response.ok or not isinstance(payload.get("result"), dict):
            raise McpServerError(f"The MCP server returned HTTP {response.status_code}")
        return payload["result"]
