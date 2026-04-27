import time
import uuid

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

import httpx
from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team, User

from products.mcp_store.backend.models import MCPServerInstallation, MCPServerInstallationTool


class TestMCPProxyEndpoint(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def setUp(self):
        super().setUp()
        patcher = patch("products.mcp_store.backend.proxy.is_url_allowed", return_value=(True, None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _proxy_url(self, installation_id: str) -> str:
        return f"/api/environments/{self.team.id}/mcp_server_installations/{installation_id}/proxy/"

    def _create_installation(
        self, auth_type="api_key", sensitive_configuration=None, **kwargs
    ) -> MCPServerInstallation:
        defaults = {
            "team": self.team,
            "user": self.user,
            "display_name": "Test Server",
            "url": "https://mcp.example.com/mcp",
            "auth_type": auth_type,
            "sensitive_configuration": sensitive_configuration or {},
        }
        defaults.update(kwargs)
        return MCPServerInstallation.objects.create(**defaults)

    def _create_oauth_installation(self, **overrides) -> MCPServerInstallation:
        sensitive = {
            "access_token": "oauth-token-123",
            "refresh_token": "refresh-token-456",
            "token_retrieved_at": int(time.time()),
            "expires_in": 3600,
            "dcr_client_id": "client-123",
            "dcr_is_user_provided": False,
        }
        sensitive.update(overrides.pop("sensitive_configuration", {}))
        overrides.setdefault(
            "oauth_metadata",
            {
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
            },
        )
        overrides.setdefault("oauth_issuer_url", "https://auth.example.com")
        return self._create_installation(
            auth_type="oauth",
            sensitive_configuration=sensitive,
            **overrides,
        )

    def _mock_client_with_response(self, mock_client_cls, mock_response):
        """Set up mock httpx.Client for the stream-based proxy pattern."""
        mock_client = MagicMock()
        mock_client.build_request.return_value = MagicMock()
        mock_client.send.return_value = mock_response
        mock_client_cls.return_value = mock_client
        return mock_client

    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_proxy_forwards_json_rpc_with_api_key(self, mock_client_cls):
        installation = self._create_installation(
            sensitive_configuration={"api_key": "sk-test-key"},
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = b'{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}'
        mock_client = self._mock_client_with_response(mock_client_cls, mock_response)

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            format="json",
        )

        assert response.status_code == 200
        _, kwargs = mock_client.build_request.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer sk-test-key"

    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_proxy_forwards_json_rpc_with_oauth_token(self, mock_client_cls):
        installation = self._create_oauth_installation()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = b'{"jsonrpc":"2.0","id":1,"result":{}}'
        mock_client = self._mock_client_with_response(mock_client_cls, mock_response)

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            format="json",
        )

        assert response.status_code == 200
        _, kwargs = mock_client.build_request.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer oauth-token-123"

    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_proxy_streams_sse_response_in_chunks(self, mock_client_cls):
        installation = self._create_installation(
            sensitive_configuration={"api_key": "sk-test-key"},
        )
        sse_chunks = [b"event: message\n", b"data: {}\n\n"]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/event-stream"}
        mock_response.iter_bytes.return_value = iter(sse_chunks)
        mock_response.close = MagicMock()
        self._mock_client_with_response(mock_client_cls, mock_response)

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            format="json",
        )

        assert response.status_code == 200
        assert "text/event-stream" in response["Content-Type"]
        content = b"".join(response.streaming_content)  # type: ignore[attr-defined]
        assert content == b"event: message\ndata: {}\n\n"
        mock_response.iter_bytes.assert_called_once_with(4096)

    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_proxy_passes_mcp_session_id_both_ways(self, mock_client_cls):
        installation = self._create_installation(
            sensitive_configuration={"api_key": "sk-test-key"},
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "content-type": "application/json",
            "mcp-session-id": "session-abc",
        }
        mock_response.content = b'{"jsonrpc":"2.0","id":1,"result":{}}'
        mock_client = self._mock_client_with_response(mock_client_cls, mock_response)

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            format="json",
            HTTP_MCP_SESSION_ID="client-session-xyz",
        )

        assert response.status_code == 200
        assert response["Mcp-Session-Id"] == "session-abc"
        _, kwargs = mock_client.build_request.call_args
        assert kwargs["headers"]["Mcp-Session-Id"] == "client-session-xyz"

    @patch("products.mcp_store.backend.oauth.refresh_oauth_token")
    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_proxy_refreshes_expired_oauth_token(self, mock_client_cls, mock_refresh):
        installation = self._create_oauth_installation(
            sensitive_configuration={
                "access_token": "expired-token",
                "refresh_token": "refresh-token-456",
                "token_retrieved_at": int(time.time()) - 7200,
                "expires_in": 3600,
            },
        )
        mock_refresh.return_value = {
            "access_token": "new-token-789",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = b'{"jsonrpc":"2.0","id":1,"result":{}}'
        mock_client = self._mock_client_with_response(mock_client_cls, mock_response)

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            format="json",
        )

        assert response.status_code == 200
        mock_refresh.assert_called_once()
        _, kwargs = mock_client.build_request.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer new-token-789"

    @patch("products.mcp_store.backend.oauth.refresh_oauth_token")
    def test_proxy_returns_401_on_refresh_failure(self, mock_refresh):
        from products.mcp_store.backend.oauth import TokenRefreshError

        installation = self._create_oauth_installation(
            sensitive_configuration={
                "access_token": "expired-token",
                "refresh_token": "refresh-token-456",
                "token_retrieved_at": int(time.time()) - 7200,
                "expires_in": 3600,
            },
        )
        mock_refresh.side_effect = TokenRefreshError("Token refresh failed")

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["error"] == "Authentication failed"

    def test_proxy_returns_403_for_disabled_installation(self):
        installation = self._create_installation(
            sensitive_configuration={"api_key": "sk-test-key"},
            is_enabled=False,
        )

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["error"] == "Server is disabled"

    def test_proxy_returns_401_for_needs_reauth(self):
        installation = self._create_oauth_installation(
            sensitive_configuration={
                "access_token": "some-token",
                "needs_reauth": True,
                "token_retrieved_at": int(time.time()),
                "expires_in": 3600,
            },
        )

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["error"] == "Installation needs re-authentication"

    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_proxy_sends_no_auth_header_for_none_auth_type(self, mock_client_cls):
        installation = self._create_installation(auth_type="none")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = b'{"jsonrpc":"2.0","id":1,"result":{}}'
        mock_client = self._mock_client_with_response(mock_client_cls, mock_response)

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            format="json",
        )

        assert response.status_code == 200
        _, kwargs = mock_client.build_request.call_args
        assert "Authorization" not in kwargs["headers"]

    @parameterized.expand(
        [
            ("connect_error", httpx.ConnectError("Connection refused"), 502, "Upstream MCP server unreachable"),
            ("timeout", httpx.TimeoutException("Timed out"), 502, "Upstream MCP server timed out"),
        ]
    )
    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_proxy_upstream_errors(self, _name, side_effect, expected_status, expected_error, mock_client_cls):
        installation = self._create_installation(
            sensitive_configuration={"api_key": "sk-test-key"},
        )
        mock_client = MagicMock()
        mock_client.build_request.return_value = MagicMock()
        mock_client.send.side_effect = side_effect
        mock_client_cls.return_value = mock_client

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            format="json",
        )

        assert response.status_code == expected_status
        assert response.json()["error"] == expected_error

    def test_proxy_returns_400_for_invalid_json(self):
        installation = self._create_installation(
            sensitive_configuration={"api_key": "sk-test-key"},
        )

        response = self.client.post(
            self._proxy_url(installation.id),
            data="not json",
            content_type="application/json",
        )

        assert response.status_code == 400

    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_proxy_passes_through_upstream_error_status(self, mock_client_cls):
        installation = self._create_installation(
            sensitive_configuration={"api_key": "sk-test-key"},
        )
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = b'{"error": "Not found"}'
        self._mock_client_with_response(mock_client_cls, mock_response)

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            format="json",
        )

        assert response.status_code == 404

    def test_proxy_returns_401_for_oauth_without_access_token(self):
        installation = self._create_oauth_installation(
            sensitive_configuration={
                "refresh_token": "refresh-only",
                "token_retrieved_at": int(time.time()),
                "expires_in": 3600,
            },
        )
        sensitive = dict(installation.sensitive_configuration)
        sensitive.pop("access_token", None)
        installation.sensitive_configuration = sensitive
        installation.save()

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["error"] == "No credentials configured"

    def test_proxy_returns_401_for_api_key_without_key(self):
        installation = self._create_installation(
            auth_type="api_key",
            sensitive_configuration={},
        )

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["error"] == "No credentials configured"

    @patch("products.mcp_store.backend.proxy.is_url_allowed")
    def test_proxy_rejects_ssrf_private_ips(self, mock_is_url_allowed):
        mock_is_url_allowed.return_value = (False, "Private IP address not allowed")
        installation = self._create_installation(
            sensitive_configuration={"api_key": "sk-test-key"},
        )

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            format="json",
        )

        assert response.status_code == 400
        assert "Private IP" in response.json()["error"]

    def test_proxy_rejects_body_over_1mb(self):
        installation = self._create_installation(
            sensitive_configuration={"api_key": "sk-test-key"},
        )
        large_payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"data": "x" * 1_100_000}}

        response = self.client.post(
            self._proxy_url(installation.id),
            data=large_payload,
            format="json",
        )

        assert response.status_code == 413
        assert response.json()["error"] == "Request body too large"


class TestMCPProxyToolApproval(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    """Verify that the proxy gates ``tools/call`` on per-tool approval state."""

    def setUp(self):
        super().setUp()
        patcher = patch("products.mcp_store.backend.proxy.is_url_allowed", return_value=(True, None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _proxy_url(self, installation_id: str) -> str:
        return f"/api/environments/{self.team.id}/mcp_server_installations/{installation_id}/proxy/"

    def _installation(self) -> MCPServerInstallation:
        return MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="Tools",
            url="https://mcp.example.com/mcp",
            auth_type="api_key",
            sensitive_configuration={"api_key": "sk"},
        )

    def _tool(self, installation, name, approval_state, removed_at=None) -> MCPServerInstallationTool:
        return MCPServerInstallationTool.objects.create(
            installation=installation,
            tool_name=name,
            approval_state=approval_state,
            last_seen_at=timezone.now(),
            removed_at=removed_at,
        )

    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_approved_tool_call_reaches_upstream(self, mock_client_cls):
        installation = self._installation()
        self._tool(installation, "search", "approved")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = b'{"jsonrpc":"2.0","id":1,"result":{}}'
        mock_client = MagicMock()
        mock_client.build_request.return_value = MagicMock()
        mock_client.send.return_value = mock_response
        mock_client_cls.return_value = mock_client

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "search"}},
            format="json",
        )

        assert response.status_code == 200
        mock_client.send.assert_called_once()

    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_needs_approval_tool_call_blocked_with_jsonrpc_error(self, mock_client_cls):
        installation = self._installation()
        self._tool(installation, "search", "needs_approval")

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 42, "method": "tools/call", "params": {"name": "search"}},
            format="json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == 42
        assert body["error"]["code"] == -32001
        assert "approval" in body["error"]["message"].lower()
        mock_client_cls.assert_not_called()

    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_do_not_use_tool_call_blocked_with_distinct_error_code(self, mock_client_cls):
        installation = self._installation()
        self._tool(installation, "delete", "do_not_use")

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "delete"}},
            format="json",
        )

        body = response.json()
        assert body["error"]["code"] == -32002
        mock_client_cls.assert_not_called()

    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_unknown_tool_returns_method_not_found(self, mock_client_cls):
        installation = self._installation()

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "ghost"}},
            format="json",
        )

        body = response.json()
        assert body["error"]["code"] == -32601
        mock_client_cls.assert_not_called()

    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_removed_tool_is_not_callable(self, mock_client_cls):
        installation = self._installation()
        self._tool(installation, "legacy", "approved", removed_at=timezone.now())

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "legacy"}},
            format="json",
        )

        body = response.json()
        assert body["error"]["code"] == -32601
        mock_client_cls.assert_not_called()

    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_non_tools_call_methods_pass_through(self, mock_client_cls):
        installation = self._installation()
        # No tools registered — but tools/list must still reach upstream.
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = b'{"jsonrpc":"2.0","id":1,"result":{}}'
        mock_client = MagicMock()
        mock_client.build_request.return_value = MagicMock()
        mock_client.send.return_value = mock_response
        mock_client_cls.return_value = mock_client

        response = self.client.post(
            self._proxy_url(installation.id),
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            format="json",
        )

        assert response.status_code == 200
        mock_client.send.assert_called_once()

    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_batch_all_approved_passes_through(self, mock_client_cls):
        installation = self._installation()
        self._tool(installation, "a", "approved")
        self._tool(installation, "b", "approved")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = b"[]"
        mock_client = MagicMock()
        mock_client.build_request.return_value = MagicMock()
        mock_client.send.return_value = mock_response
        mock_client_cls.return_value = mock_client

        response = self.client.post(
            self._proxy_url(installation.id),
            data=[
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "a"}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "b"}},
            ],
            format="json",
        )

        assert response.status_code == 200
        mock_client.send.assert_called_once()

    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_batch_all_blocked_returns_jsonrpc_error_list(self, mock_client_cls):
        installation = self._installation()
        self._tool(installation, "a", "needs_approval")
        self._tool(installation, "b", "do_not_use")

        response = self.client.post(
            self._proxy_url(installation.id),
            data=[
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "a"}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "b"}},
            ],
            format="json",
        )

        body = response.json()
        assert isinstance(body, list)
        assert [entry["error"]["code"] for entry in body] == [-32001, -32002]
        mock_client_cls.assert_not_called()

    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_mixed_batch_rejects_whole_request_with_batch_code(self, mock_client_cls):
        """Mixed batches are rejected atomically with a batch-level code, not a per-item code."""
        installation = self._installation()
        self._tool(installation, "approved-tool", "approved")
        self._tool(installation, "unapproved-tool", "needs_approval")

        response = self.client.post(
            self._proxy_url(installation.id),
            data=[
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "approved-tool"}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "unapproved-tool"}},
            ],
            format="json",
        )

        body = response.json()
        assert isinstance(body, list)
        # Every item gets the batch-level code; the per-item -32001/-32002 codes
        # would wrongly imply the siblings themselves need approval or are disabled.
        for entry in body:
            assert entry["error"]["code"] == -32000
        mock_client_cls.assert_not_called()

    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_mixed_batch_with_tools_list_sibling_uses_batch_code(self, mock_client_cls):
        """A passthrough sibling like tools/list must not get TOOL_NEEDS_APPROVAL_CODE."""
        installation = self._installation()
        self._tool(installation, "unapproved-tool", "needs_approval")

        response = self.client.post(
            self._proxy_url(installation.id),
            data=[
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "unapproved-tool"}},
            ],
            format="json",
        )

        body = response.json()
        assert isinstance(body, list)
        assert [entry["error"]["code"] for entry in body] == [-32000, -32000]
        # The tools/list sibling specifically must not inherit the approval code.
        tools_list_entry = next(e for e in body if e["id"] == 1)
        assert tools_list_entry["error"]["code"] != -32001
        mock_client_cls.assert_not_called()


class TestMCPProxyAccessControl(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    """Verify that the proxy endpoint enforces team and user isolation."""

    JSON_RPC_BODY = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}

    def setUp(self):
        super().setUp()
        patcher = patch("products.mcp_store.backend.proxy.is_url_allowed", return_value=(True, None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _proxy_url(self, installation_id: str, team_id: int | None = None) -> str:
        tid = team_id if team_id is not None else self.team.id
        return f"/api/environments/{tid}/mcp_server_installations/{installation_id}/proxy/"

    def _create_installation(self, team, user, **kwargs) -> MCPServerInstallation:
        defaults = {
            "team": team,
            "user": user,
            "display_name": "Test Server",
            "url": f"https://mcp-{uuid.uuid4().hex[:8]}.example.com/mcp",
            "auth_type": "api_key",
            "sensitive_configuration": {"api_key": "sk-secret"},
        }
        defaults.update(kwargs)
        return MCPServerInstallation.objects.create(**defaults)

    def test_proxy_denies_access_to_other_users_installation_same_team(self):
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        installation = self._create_installation(self.team, other_user)

        response = self.client.post(self._proxy_url(installation.id), data=self.JSON_RPC_BODY, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_proxy_denies_access_to_installation_in_other_team(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_user = User.objects.create_and_join(other_org, "alien@other.com", "password")
        installation = self._create_installation(other_team, other_user)

        response = self.client.post(
            self._proxy_url(installation.id, team_id=other_team.id), data=self.JSON_RPC_BODY, format="json"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_proxy_denies_cross_team_id_spoofing(self):
        """URL uses team B's id but user is only a member of team A."""
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_user = User.objects.create_and_join(other_org, "alien@other.com", "password")
        installation = self._create_installation(other_team, other_user)

        response = self.client.post(
            self._proxy_url(installation.id, team_id=other_team.id), data=self.JSON_RPC_BODY, format="json"
        )

        assert response.status_code in (
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND,
        )

    def test_proxy_denies_unauthenticated_request(self):
        installation = self._create_installation(self.team, self.user)
        self.client.logout()

        response = self.client.post(self._proxy_url(installation.id), data=self.JSON_RPC_BODY, format="json")

        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_proxy_returns_404_for_nonexistent_installation(self):
        fake_id = uuid.uuid4()

        response = self.client.post(self._proxy_url(str(fake_id)), data=self.JSON_RPC_BODY, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_proxy_does_not_leak_other_users_credentials(self, mock_client_cls):
        """Even if the installation UUID is known, another user's secret must not be forwarded."""
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        installation = self._create_installation(
            self.team,
            other_user,
            sensitive_configuration={"api_key": "sk-victim-secret"},
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = b'{"jsonrpc":"2.0","id":1,"result":{}}'
        self._mock_client_with_response(mock_client_cls, mock_response)

        response = self.client.post(self._proxy_url(installation.id), data=self.JSON_RPC_BODY, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_client_cls.assert_not_called()

    def _mock_client_with_response(self, mock_client_cls, mock_response):
        mock_client = MagicMock()
        mock_client.build_request.return_value = MagicMock()
        mock_client.send.return_value = mock_response
        mock_client_cls.return_value = mock_client
        return mock_client

    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_proxy_scopes_to_authenticated_user_not_installation_owner(self, mock_client_cls):
        """The requesting user's identity gates access, not the installation's user field."""
        installation = self._create_installation(self.team, self.user)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = b'{"jsonrpc":"2.0","id":1,"result":{}}'
        self._mock_client_with_response(mock_client_cls, mock_response)

        # Owner can access
        response = self.client.post(self._proxy_url(installation.id), data=self.JSON_RPC_BODY, format="json")
        assert response.status_code == 200

        # Different user in the same team cannot
        other_user = User.objects.create_and_join(self.organization, "colleague@posthog.com", "password")
        self.client.force_login(other_user)
        response = self.client.post(self._proxy_url(installation.id), data=self.JSON_RPC_BODY, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_proxy_rejects_get_and_other_http_methods(self):
        installation = self._create_installation(self.team, self.user)
        url = self._proxy_url(installation.id)

        for method in ("get", "put", "patch", "delete"):
            response = getattr(self.client, method)(url, data=self.JSON_RPC_BODY, format="json")
            assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED, (
                f"Expected 405 for {method.upper()}, got {response.status_code}"
            )
