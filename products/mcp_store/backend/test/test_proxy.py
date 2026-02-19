import time

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from unittest.mock import MagicMock, patch

import httpx
from parameterized import parameterized
from rest_framework import status

from products.mcp_store.backend.models import MCPServer, MCPServerInstallation


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
        server = MCPServer.objects.create(
            name="OAuth Server",
            url="https://auth.example.com",
            oauth_client_id="client-123",
            oauth_metadata={
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
            },
            created_by=self.user,
        )
        sensitive = {
            "access_token": "oauth-token-123",
            "refresh_token": "refresh-token-456",
            "token_retrieved_at": int(time.time()),
            "expires_in": 3600,
        }
        sensitive.update(overrides.pop("sensitive_configuration", {}))
        return self._create_installation(
            auth_type="oauth",
            sensitive_configuration=sensitive,
            server=server,
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
        content = b"".join(response.streaming_content)
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

    @patch("products.mcp_store.backend.proxy.refresh_oauth_token")
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

    @patch("products.mcp_store.backend.proxy.refresh_oauth_token")
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
