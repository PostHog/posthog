from collections.abc import Callable
from typing import Any, TypeVar

from django.conf import settings

import requests

from posthog.models import User

from ..facade.contracts import ExecResult, ExecTool, McpServerError, McpServerUnauthorizedError
from .tokens import WebMCPTokenIssuer

# The stateless MCP dialect needs no handshake, so each proxied call is one HTTP request.
PROTOCOL_VERSION = "2026-07-28"
CLIENT_INFO = {"name": "posthog-webmcp", "version": "1.0.0"}
EXEC_TOOL_NAME = "exec"
# Connect, read. The read timeout covers slow tools such as SQL queries.
REQUEST_TIMEOUT_SECONDS = (5, 120)

T = TypeVar("T")


class McpServerClient:
    """Talks to the PostHog MCP server in single-`exec` mode."""

    def __init__(self, *, url: str, token: str) -> None:
        self._url = url
        self._token = token

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
            response = requests.post(self._url, json=body, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as error:
            raise McpServerError(f"Could not reach the MCP server: {error.__class__.__name__}") from error

        if response.status_code == 401:
            raise McpServerUnauthorizedError("The MCP server rejected the access token")
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


class WebMCPProxy:
    """Runs MCP calls for one user and team, with a token exchanged for their session."""

    def __init__(self, user: User, team_id: int, *, issuer: WebMCPTokenIssuer, url: str) -> None:
        self._user = user
        self._team_id = team_id
        self._issuer = issuer
        self._url = url

    @classmethod
    def for_user(cls, user: User, team_id: int) -> "WebMCPProxy":
        if not settings.MCP_SERVER_URL:
            raise McpServerError("WebMCP is not available on this instance")
        # Every request carries a bearer token for the user, so plain HTTP is for a local MCP server only.
        if not settings.MCP_SERVER_URL.startswith("https://") and not settings.DEBUG:
            raise McpServerError("WebMCP needs an HTTPS MCP server URL")
        return cls(user, team_id, issuer=WebMCPTokenIssuer.for_instance(), url=settings.MCP_SERVER_URL)

    def get_exec_tool(self) -> ExecTool:
        return self._call(lambda client: client.get_exec_tool())

    def run_exec(self, command: str) -> ExecResult:
        return self._call(lambda client: client.call_exec(command))

    def _call(self, operation: Callable[[McpServerClient], T]) -> T:
        token = self._issuer.get_or_mint(self._user, self._team_id)
        try:
            return operation(McpServerClient(url=self._url, token=token))
        except McpServerUnauthorizedError:
            # The user can revoke a reused token from their connected apps before it expires.
            fresh_token = self._issuer.mint(self._user, self._team_id)
            return operation(McpServerClient(url=self._url, token=fresh_token))
