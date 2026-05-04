import json
import uuid

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.utils import timezone

import httpx

from products.mcp_store.backend.models import MCPServerInstallation, MCPServerInstallationTool
from products.mcp_store.backend.tools import (
    HANDSHAKE_TIMEOUT,
    ToolsFetchError,
    fetch_upstream_tools,
    sync_installation_tools,
)


def _build_response(
    *, status: int = 200, body: str = "", content_type: str = "application/json", session_id: str | None = None
) -> MagicMock:
    """Build a MagicMock that looks enough like an httpx.Response for our code.

    Our parser reads ``status_code``, ``text``, and ``headers`` — so we set those
    explicitly rather than relying on MagicMock auto-spec.
    """
    response = MagicMock()
    response.status_code = status
    response.text = body
    headers: dict[str, str] = {"content-type": content_type}
    if session_id is not None:
        headers["mcp-session-id"] = session_id
    response.headers = headers
    return response


def _install_handshake_mock(
    mock_client_cls: MagicMock, *, tools_list_response: MagicMock, session_id: str | None = "sess-1"
) -> MagicMock:
    """Wire up the httpx.Client mock for the full MCP handshake.

    Returns the client mock so tests can assert against call order / arguments.
    The handshake is: POST initialize → POST notifications/initialized → POST
    tools/list → DELETE. Tests parameterize the tools/list response.
    """
    initialize_body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}})
    initialize_resp = _build_response(body=initialize_body, session_id=session_id)
    notify_resp = _build_response(status=202, body="")

    client = MagicMock()
    # Three POSTs in order: initialize, notifications/initialized, tools/list.
    client.post.side_effect = [initialize_resp, notify_resp, tools_list_response]
    client.delete.return_value = _build_response(status=200, body="")
    mock_client_cls.return_value.__enter__.return_value = client
    return client


class TestFetchUpstreamTools(ClickhouseTestMixin, APIBaseTest):
    def _installation(self, **overrides) -> MCPServerInstallation:
        defaults = {
            "team": self.team,
            "user": self.user,
            "url": f"https://mcp-{uuid.uuid4().hex[:8]}.example.com/mcp",
            "display_name": "Test",
            "auth_type": "api_key",
            "sensitive_configuration": {"api_key": "sk-test"},
        }
        defaults.update(overrides)
        return MCPServerInstallation.objects.create(**defaults)

    @patch("products.mcp_store.backend.tools.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.tools.httpx.Client")
    def test_fetch_upstream_tools_uses_handshake_timeout(self, mock_client_cls, _allow):
        # The handshake must not inherit the proxy's 180s budget — that would let a
        # slow upstream hold a Django worker for minutes.
        installation = self._installation()
        tools_body = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "alpha"}]}})
        _install_handshake_mock(mock_client_cls, tools_list_response=_build_response(body=tools_body))

        fetch_upstream_tools(installation)

        assert mock_client_cls.call_args.kwargs["timeout"] == HANDSHAKE_TIMEOUT
        assert HANDSHAKE_TIMEOUT <= 30  # guard against accidental regression

    @patch("products.mcp_store.backend.tools.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.tools.httpx.Client")
    def test_fetch_upstream_tools_parses_result(self, mock_client_cls, _allow):
        installation = self._installation()
        tools_body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "tools": [
                        {"name": "alpha", "description": "A", "inputSchema": {"type": "object"}},
                        {"name": "beta", "title": "Beta!", "description": "B"},
                        {"description": "no name"},  # invalid — dropped
                    ]
                },
            }
        )
        client = _install_handshake_mock(mock_client_cls, tools_list_response=_build_response(body=tools_body))

        tools = fetch_upstream_tools(installation)
        assert [t["name"] for t in tools] == ["alpha", "beta"]

        # Verify the handshake order and that the session id rode along on later calls.
        assert client.post.call_count == 3
        init_call, notify_call, list_call = client.post.call_args_list
        assert json.loads(init_call.kwargs["content"])["method"] == "initialize"
        assert "Mcp-Session-Id" not in init_call.kwargs["headers"]
        assert json.loads(notify_call.kwargs["content"])["method"] == "notifications/initialized"
        assert notify_call.kwargs["headers"]["Mcp-Session-Id"] == "sess-1"
        assert json.loads(list_call.kwargs["content"])["method"] == "tools/list"
        assert list_call.kwargs["headers"]["Authorization"] == "Bearer sk-test"
        assert list_call.kwargs["headers"]["Mcp-Session-Id"] == "sess-1"
        # DELETE cleans up the session afterwards.
        assert client.delete.called
        assert client.delete.call_args.kwargs["headers"]["Mcp-Session-Id"] == "sess-1"

    @patch("products.mcp_store.backend.tools.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.tools.httpx.Client")
    def test_fetch_upstream_tools_parses_sse_tools_list(self, mock_client_cls, _allow):
        # Some MCP servers reply to tools/list over SSE even though initialize
        # came back as JSON. Make sure we still extract the tool array.
        installation = self._installation()
        sse_body = 'event: message\ndata: {"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"alpha"}]}}\n\n'
        _install_handshake_mock(
            mock_client_cls,
            tools_list_response=_build_response(body=sse_body, content_type="text/event-stream"),
        )

        tools = fetch_upstream_tools(installation)
        assert [t["name"] for t in tools] == ["alpha"]

    @patch("products.mcp_store.backend.tools.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.tools.httpx.Client")
    def test_fetch_upstream_tools_works_without_session_id(self, mock_client_cls, _allow):
        # Servers that don't require a session simply omit Mcp-Session-Id on the
        # initialize response. We should still complete the handshake and not
        # send DELETE (nothing to terminate).
        installation = self._installation()
        tools_body = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "alpha"}]}})
        client = _install_handshake_mock(
            mock_client_cls,
            tools_list_response=_build_response(body=tools_body),
            session_id=None,  # no session id returned
        )
        # _install_handshake_mock still queues an initialize with a session id;
        # overwrite that so this case is accurate.
        init_resp = _build_response(body=json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}))
        notify_resp = _build_response(status=202, body="")
        client.post.side_effect = [init_resp, notify_resp, _build_response(body=tools_body)]

        tools = fetch_upstream_tools(installation)
        assert [t["name"] for t in tools] == ["alpha"]
        assert not client.delete.called

    @patch("products.mcp_store.backend.tools.is_url_allowed", return_value=(False, "Private IP"))
    def test_fetch_upstream_tools_raises_on_blocked_url(self, _allow):
        installation = self._installation()
        with pytest.raises(ToolsFetchError, match="URL not allowed"):
            fetch_upstream_tools(installation)

    @patch("products.mcp_store.backend.tools.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.tools.httpx.Client")
    def test_fetch_upstream_tools_raises_on_connect_error(self, mock_client_cls, _allow):
        installation = self._installation()
        client = MagicMock()
        client.post.side_effect = httpx.ConnectError("nope")
        mock_client_cls.return_value.__enter__.return_value = client

        with pytest.raises(ToolsFetchError, match="unreachable"):
            fetch_upstream_tools(installation)

    @patch("products.mcp_store.backend.tools.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.tools.httpx.Client")
    def test_fetch_upstream_tools_raises_on_initialize_error(self, mock_client_cls, _allow):
        installation = self._installation()
        client = MagicMock()
        client.post.return_value = _build_response(status=401, body="Unauthorized")
        mock_client_cls.return_value.__enter__.return_value = client

        with pytest.raises(ToolsFetchError, match="initialize returned status 401"):
            fetch_upstream_tools(installation)

    @patch("products.mcp_store.backend.tools.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.tools.httpx.Client")
    def test_fetch_upstream_tools_raises_when_result_missing(self, mock_client_cls, _allow):
        installation = self._installation()
        tools_body = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {}})
        _install_handshake_mock(mock_client_cls, tools_list_response=_build_response(body=tools_body))

        with pytest.raises(ToolsFetchError, match="missing 'result.tools'"):
            fetch_upstream_tools(installation)


class TestSyncInstallationTools(ClickhouseTestMixin, APIBaseTest):
    def _installation(self) -> MCPServerInstallation:
        return MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            url=f"https://mcp-{uuid.uuid4().hex[:8]}.example.com/mcp",
            display_name="Test",
            auth_type="api_key",
            sensitive_configuration={"api_key": "sk-test"},
        )

    @patch("products.mcp_store.backend.tools.fetch_upstream_tools")
    def test_new_tools_default_to_needs_approval(self, mock_fetch):
        installation = self._installation()
        mock_fetch.return_value = [{"name": "search", "description": "Search something"}]

        sync_installation_tools(installation)
        tool = installation.tools.get(tool_name="search")
        assert tool.approval_state == "needs_approval"
        assert tool.description == "Search something"
        assert tool.removed_at is None

    @patch("products.mcp_store.backend.tools.fetch_upstream_tools")
    def test_disappeared_tool_marked_removed_state_preserved(self, mock_fetch):
        installation = self._installation()
        mock_fetch.return_value = [{"name": "search"}]
        sync_installation_tools(installation)

        tool = installation.tools.get(tool_name="search")
        tool.approval_state = "approved"
        tool.save(update_fields=["approval_state"])

        mock_fetch.return_value = []  # upstream dropped the tool
        sync_installation_tools(installation)
        tool.refresh_from_db()
        assert tool.removed_at is not None
        # Approval survives a disappearance so a returning tool isn't quietly downgraded.
        assert tool.approval_state == "approved"

    @patch("products.mcp_store.backend.tools.fetch_upstream_tools")
    def test_reappearing_tool_clears_removed_and_keeps_state(self, mock_fetch):
        installation = self._installation()
        # Seed a removed tool with a manually-chosen approval state.
        MCPServerInstallationTool.objects.create(
            installation=installation,
            tool_name="write",
            description="old",
            approval_state="do_not_use",
            last_seen_at=timezone.now(),
            removed_at=timezone.now(),
        )

        mock_fetch.return_value = [{"name": "write", "description": "updated"}]
        sync_installation_tools(installation)

        tool = installation.tools.get(tool_name="write")
        assert tool.removed_at is None
        # Returning tools keep whatever the user set last.
        assert tool.approval_state == "do_not_use"
        assert tool.description == "updated"

    @patch("products.mcp_store.backend.tools.fetch_upstream_tools")
    def test_existing_tool_metadata_updates_but_approval_preserved(self, mock_fetch):
        installation = self._installation()
        MCPServerInstallationTool.objects.create(
            installation=installation,
            tool_name="search",
            description="old description",
            input_schema={"type": "object"},
            approval_state="approved",
            last_seen_at=timezone.now(),
        )

        mock_fetch.return_value = [
            {
                "name": "search",
                "description": "new description",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
            }
        ]
        sync_installation_tools(installation)

        tool = installation.tools.get(tool_name="search")
        assert tool.description == "new description"
        assert "properties" in tool.input_schema
        assert tool.approval_state == "approved"
