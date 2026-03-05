from urllib.parse import urlparse

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APIClient

from products.mcp_store.backend.models import RECOMMENDED_SERVERS, MCPServer, MCPServerInstallation

ALLOW_URL = patch("products.mcp_store.backend.api.is_url_allowed", return_value=(True, None))


class TestMCPServerAPI(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def test_list_servers_returns_static_catalog(self):
        response = self.client.get(f"/api/environments/{self.team.id}/mcp_servers/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        names = {s["name"] for s in results}
        expected_names = {s["name"] for s in RECOMMENDED_SERVERS}
        assert names == expected_names

    def test_list_servers_entries_match_serializer_schema(self):
        response = self.client.get(f"/api/environments/{self.team.id}/mcp_servers/")
        expected_keys = {"name", "url", "description", "icon_url", "auth_type", "oauth_provider_kind"}
        for entry in response.json()["results"]:
            assert set(entry.keys()) == expected_keys

    def test_create_not_allowed(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_servers/",
            data={"name": "My Server", "url": "https://mcp.example.com"},
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_unauthenticated_access(self):
        client = APIClient()
        response = client.get(f"/api/environments/{self.team.id}/mcp_servers/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestMCPServerInstallationAPI(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def _create_server(self, **kwargs) -> MCPServer:
        defaults = {
            "name": "Test Server",
            "url": "https://mcp.example.com",
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return MCPServer.objects.create(**defaults)

    def test_create_not_allowed(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/",
            data={"url": "https://mcp.example.com", "display_name": "Test"},
            format="json",
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_list_installations(self):
        server = self._create_server()
        MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            server=server,
            display_name=server.name,
            url=server.url,
            auth_type="api_key",
        )

        response = self.client.get(f"/api/environments/{self.team.id}/mcp_server_installations/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["server_id"] == str(server.id)

    def test_uninstall_server(self):
        server = self._create_server()
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            server=server,
            display_name=server.name,
            url=server.url,
            auth_type="api_key",
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not MCPServerInstallation.objects.filter(id=installation.id).exists()

    def test_update_installation(self):
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="Original",
            url="https://mcp.example.com",
            description="Old description",
            auth_type="api_key",
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/",
            data={"display_name": "Updated", "description": "New description"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["display_name"] == "Updated"
        assert response.json()["name"] == "Updated"
        assert response.json()["description"] == "New description"

    def test_user_isolation(self):
        server = self._create_server()
        MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            server=server,
            display_name=server.name,
            url=server.url,
            auth_type="api_key",
        )

        from posthog.models import User

        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        other_installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=other_user,
            server=server,
            display_name=server.name,
            url="https://mcp2.example.com",
            auth_type="api_key",
        )

        response = self.client.get(f"/api/environments/{self.team.id}/mcp_server_installations/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["id"] != str(other_installation.id)

    def test_installation_without_server_has_null_server_id(self):
        MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="Custom",
            url="https://mcp.custom.com",
            auth_type="api_key",
        )

        response = self.client.get(f"/api/environments/{self.team.id}/mcp_server_installations/")
        assert response.status_code == status.HTTP_200_OK
        result = response.json()["results"][0]
        assert result["server_id"] is None


class TestInstallCustomAPI(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    @ALLOW_URL
    def test_install_custom_api_key_server(self, _mock):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={
                "name": "My API Server",
                "url": "https://mcp.custom.com",
                "auth_type": "api_key",
                "api_key": "sk-test-123",
                "description": "A custom server",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["name"] == "My API Server"
        assert response.json()["url"] == "https://mcp.custom.com"
        assert response.json()["auth_type"] == "api_key"
        assert response.json()["server_id"] is None
        assert not MCPServer.objects.filter(url="https://mcp.custom.com").exists()

    @ALLOW_URL
    def test_install_custom_api_key_server_without_key(self, _mock):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Open Server", "url": "https://mcp.open.com", "auth_type": "api_key"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["auth_type"] == "api_key"
        assert response.json()["server_id"] is None

    def test_install_custom_none_auth_type_rejected(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Server", "url": "https://mcp.example.com", "auth_type": "none"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @ALLOW_URL
    def test_install_custom_duplicate_url_rejected(self, _mock):
        self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Server", "url": "https://mcp.dup.com", "auth_type": "api_key"},
            format="json",
        )
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Server Again", "url": "https://mcp.dup.com", "auth_type": "api_key"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.mcp_store.backend.api.is_url_allowed", return_value=(False, "Private IP"))
    def test_install_custom_ssrf_blocked(self, _mock):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Evil", "url": "http://192.168.1.1/mcp", "auth_type": "api_key"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.mcp_store.backend.api.is_url_allowed", return_value=(False, "Local/metadata host"))
    def test_install_custom_oauth_ssrf_blocked(self, _mock):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={
                "name": "Evil OAuth",
                "url": "http://169.254.169.254/mcp",
                "auth_type": "oauth",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @ALLOW_URL
    def test_installation_name_field(self, _mock):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Custom Name", "url": "https://mcp.named.com", "auth_type": "api_key"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["display_name"] == "Custom Name"
        assert response.json()["name"] == "Custom Name"


class TestOAuthCallback(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def _create_server(self, **kwargs) -> MCPServer:
        defaults = {
            "name": "Test Server",
            "url": "https://auth.example.com",
            "oauth_metadata": {
                "issuer": "https://auth.example.com",
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
                "registration_endpoint": "https://auth.example.com/register",
            },
            "oauth_client_id": "dcr-client-id",
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return MCPServer.objects.create(**defaults)

    def _callback_url(self):
        return f"/api/environments/{self.team.id}/mcp_server_installations/oauth_callback/"

    @ALLOW_URL
    @patch("products.mcp_store.backend.api.requests.post")
    def test_dcr_path_used_when_pkce_cookie_present_even_with_known_provider(self, mock_post, _allow):
        """When a server has oauth_provider_kind set but the authorization went through
        DCR (indicated by the ph_pkce_verifier cookie), the token exchange must use the
        DCR token endpoint, not the known provider's endpoint."""
        server = self._create_server(oauth_provider_kind="linear")
        MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            server=server,
            url="https://mcp.example.com",
            display_name="Test",
            auth_type="oauth",
        )

        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "tok_dcr", "token_type": "bearer"}

        state_token = "test-state-token"
        self.client.cookies["ph_oauth_state"] = state_token
        self.client.cookies["ph_pkce_verifier"] = "test-pkce-verifier"

        response = self.client.post(
            self._callback_url(),
            data={"code": "auth-code", "server_id": str(server.id), "state_token": state_token},
            format="json",
        )

        assert response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED)
        # The token exchange should have been sent to the DCR token endpoint
        mock_post.assert_called_once()
        assert mock_post.call_args[0][0] == "https://auth.example.com/token"
        assert mock_post.call_args[1]["data"]["code_verifier"] == "test-pkce-verifier"

    @ALLOW_URL
    @patch("products.mcp_store.backend.api.requests.post")
    @patch("products.mcp_store.backend.api.OauthIntegration.oauth_config_for_kind")
    def test_known_provider_path_used_when_no_pkce_cookie(self, mock_config, mock_post, _allow):
        """When there is no ph_pkce_verifier cookie and the server has oauth_provider_kind,
        the known provider token exchange should be used."""
        from posthog.models.integration import OauthConfig

        server = self._create_server(oauth_provider_kind="linear")
        MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            server=server,
            url="https://mcp.example.com",
            display_name="Test",
            auth_type="oauth",
        )

        mock_config.return_value = OauthConfig(
            authorize_url="https://linear.app/oauth/authorize",
            token_url="https://api.linear.app/oauth/token",
            client_id="known-client-id",
            client_secret="known-secret",
            scope="read",
            id_path="id",
            name_path="name",
        )
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "tok_known", "token_type": "bearer"}

        state_token = "test-state-token"
        self.client.cookies["ph_oauth_state"] = state_token
        # No ph_pkce_verifier cookie — known provider path should be used

        response = self.client.post(
            self._callback_url(),
            data={"code": "auth-code", "server_id": str(server.id), "state_token": state_token},
            format="json",
        )

        assert response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED)
        mock_post.assert_called_once()
        assert mock_post.call_args[0][0] == "https://api.linear.app/oauth/token"
        assert "code_verifier" not in mock_post.call_args[1].get("data", {})


class TestOAuthIssuerSpoofingProtection(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    @ALLOW_URL
    @patch("products.mcp_store.backend.api.discover_oauth_metadata")
    def test_spoofed_issuer_fails_and_no_state_persisted(self, mock_discover, _allow):
        mock_discover.side_effect = ValueError("Issuer mismatch in authorization server metadata")

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Evil", "url": "https://evil.com/mcp", "auth_type": "oauth"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not MCPServerInstallation.objects.filter(url="https://evil.com/mcp").exists()
        assert not MCPServer.objects.filter(url="https://evil.com").exists()

    @ALLOW_URL
    @patch("products.mcp_store.backend.api.register_dcr_client")
    @patch("products.mcp_store.backend.api.discover_oauth_metadata")
    def test_existing_server_metadata_not_overwritten_on_reregistration(self, mock_discover, mock_dcr, _allow):
        legitimate_metadata = {
            "issuer": "https://auth.legit.com",
            "authorization_endpoint": "https://auth.legit.com/authorize",
            "token_endpoint": "https://auth.legit.com/token",
            "registration_endpoint": "https://auth.legit.com/register",
            "dcr_redirect_uri": "https://old.posthog.com/callback",
        }
        server = MCPServer.objects.create(
            name="Legit Server",
            url="https://auth.legit.com",
            oauth_metadata=legitimate_metadata,
            oauth_client_id="legit-client-id",
            created_by=self.user,
        )

        mock_discover.return_value = {
            "issuer": "https://auth.legit.com",
            "authorization_endpoint": "https://evil.com/authorize",
            "token_endpoint": "https://evil.com/token",
            "registration_endpoint": "https://evil.com/register",
        }
        mock_dcr.return_value = "new-client-id"

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Legit", "url": "https://legit.com/mcp", "auth_type": "oauth"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert urlparse(response.json()["redirect_url"]).netloc == "auth.legit.com"

        server.refresh_from_db()
        assert server.oauth_metadata["authorization_endpoint"] == "https://auth.legit.com/authorize"
        assert server.oauth_metadata["token_endpoint"] == "https://auth.legit.com/token"
        assert server.oauth_metadata["registration_endpoint"] == "https://auth.legit.com/register"
        assert server.oauth_client_id == "new-client-id"

        # DCR was called with the existing trusted metadata, not the attacker-supplied metadata
        mock_dcr.assert_called_once()
        call_metadata = mock_dcr.call_args[0][0]
        assert call_metadata["registration_endpoint"] == "https://auth.legit.com/register"

    @ALLOW_URL
    @patch("products.mcp_store.backend.api.register_dcr_client")
    @patch("products.mcp_store.backend.api.discover_oauth_metadata")
    def test_authorize_reuses_existing_metadata_instead_of_rediscovering(self, mock_discover, mock_dcr, _allow):
        server = MCPServer.objects.create(
            name="Server",
            url="https://auth.example.com",
            oauth_metadata={
                "issuer": "https://auth.example.com",
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
                "registration_endpoint": "https://auth.example.com/register",
                "dcr_redirect_uri": "https://old.posthog.com/callback",
            },
            oauth_client_id="existing-client-id",
            created_by=self.user,
        )
        MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            server=server,
            url="https://mcp.example.com",
            display_name="Test",
            auth_type="oauth",
        )
        mock_dcr.return_value = "new-client-id"

        response = self.client.get(
            f"/api/environments/{self.team.id}/mcp_server_installations/authorize/",
            {"server_id": str(server.id)},
        )

        assert response.status_code == 302
        assert urlparse(response["Location"]).netloc == "auth.example.com"
        mock_discover.assert_not_called()
        mock_dcr.assert_called_once()
        call_metadata = mock_dcr.call_args[0][0]
        assert call_metadata["authorization_endpoint"] == "https://auth.example.com/authorize"
