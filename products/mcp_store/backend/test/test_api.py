from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APIClient

from products.mcp_store.backend.models import MCPServer, MCPServerInstallation

ALLOW_URL = patch("products.mcp_store.backend.api.is_url_allowed", return_value=(True, None))


class TestMCPServerAPI(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def test_list_servers_returns_static_catalog(self):
        response = self.client.get(f"/api/environments/{self.team.id}/mcp_servers/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 3
        names = [s["name"] for s in results]
        assert "PostHog MCP" in names
        assert "Linear" in names
        assert "Notion" in names

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
            auth_type="none",
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
            auth_type="none",
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

    def test_update_installation_api_key(self):
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="API Server",
            url="https://mcp.example.com",
            auth_type="api_key",
            sensitive_configuration={"api_key": "old-key"},
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/",
            data={"configuration": {"api_key": "new-key"}},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        installation.refresh_from_db()
        assert installation.sensitive_configuration["api_key"] == "new-key"

    def test_user_isolation(self):
        server = self._create_server()
        MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            server=server,
            display_name=server.name,
            url=server.url,
            auth_type="none",
        )

        from posthog.models import User

        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        other_installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=other_user,
            server=server,
            display_name=server.name,
            url="https://mcp2.example.com",
            auth_type="none",
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
            auth_type="none",
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
    def test_install_custom_no_auth_server(self, _mock):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Open Server", "url": "https://mcp.open.com", "auth_type": "none"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["auth_type"] == "none"
        assert response.json()["server_id"] is None

    @ALLOW_URL
    def test_install_custom_duplicate_url_rejected(self, _mock):
        self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Server", "url": "https://mcp.dup.com", "auth_type": "none"},
            format="json",
        )
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Server Again", "url": "https://mcp.dup.com", "auth_type": "none"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.mcp_store.backend.api.is_url_allowed", return_value=(False, "Private IP"))
    def test_install_custom_ssrf_blocked(self, _mock):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Evil", "url": "http://192.168.1.1/mcp", "auth_type": "none"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @ALLOW_URL
    def test_installation_name_field(self, _mock):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Custom Name", "url": "https://mcp.named.com", "auth_type": "none"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["display_name"] == "Custom Name"
        assert response.json()["name"] == "Custom Name"
