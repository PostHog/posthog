from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.team.team import Team

from products.mcp_store.backend.models import MCPServer, MCPServerInstallation


class TestMCPServerAPI(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def _create_server(self, **kwargs) -> MCPServer:
        defaults = {
            "name": "Test Server",
            "url": "https://mcp.example.com",
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return MCPServer.objects.create(**defaults)

    def test_create_server(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_servers/",
            data={"name": "My Server", "url": "https://mcp.example.com", "auth_type": "api_key"},
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["name"] == "My Server"
        assert response.json()["url"] == "https://mcp.example.com"
        assert response.json()["auth_type"] == "api_key"
        assert response.json()["is_default"] is False

    def test_list_servers(self):
        self._create_server(name="Server 1", url="https://mcp1.example.com")
        self._create_server(name="Server 2", url="https://mcp2.example.com")

        response = self.client.get(f"/api/environments/{self.team.id}/mcp_servers/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 2

    def test_servers_are_platform_level(self):
        self._create_server(name="Global Server", url="https://mcp.global.com")

        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        response = self.client.get(f"/api/environments/{team2.id}/mcp_servers/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["name"] == "Global Server"

    def test_retrieve_server(self):
        server = self._create_server()
        response = self.client.get(f"/api/environments/{self.team.id}/mcp_servers/{server.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Test Server"

    def test_delete_server(self):
        server = self._create_server()
        response = self.client.delete(f"/api/environments/{self.team.id}/mcp_servers/{server.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not MCPServer.objects.filter(id=server.id).exists()

    def test_duplicate_url_rejected(self):
        self._create_server(url="https://mcp.example.com")
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_servers/",
            data={"name": "Duplicate", "url": "https://mcp.example.com"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.mcp_store.backend.api.is_url_allowed", return_value=(False, "Disallowed scheme"))
    def test_ssrf_disallowed_scheme_blocked(self, _mock):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_servers/",
            data={"name": "Evil", "url": "file:///etc/passwd"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.mcp_store.backend.api.is_url_allowed", return_value=(False, "Local/metadata host"))
    def test_ssrf_metadata_endpoint_blocked(self, _mock):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_servers/",
            data={"name": "Evil", "url": "http://169.254.169.254/latest/meta-data/"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.mcp_store.backend.api.is_url_allowed", return_value=(False, "Private IP address not allowed"))
    def test_ssrf_private_ip_blocked(self, _mock):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_servers/",
            data={"name": "Evil", "url": "http://192.168.1.1/mcp"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.mcp_store.backend.api.is_url_allowed", return_value=(False, "Local/Loopback host not allowed"))
    def test_ssrf_localhost_blocked(self, _mock):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_servers/",
            data={"name": "Evil", "url": "http://localhost:8000/mcp"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

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

    def test_install_server(self):
        server = self._create_server()
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/",
            data={"server_id": str(server.id), "url": server.url, "display_name": server.name},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["server"]["id"] == str(server.id)
        assert response.json()["name"] == "Test Server"

    def test_list_installations(self):
        server = self._create_server()
        MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            server=server,
            display_name=server.name,
            url=server.url,
            auth_type=server.auth_type,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/mcp_server_installations/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1

    def test_uninstall_server(self):
        server = self._create_server()
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            server=server,
            display_name=server.name,
            url=server.url,
            auth_type=server.auth_type,
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not MCPServerInstallation.objects.filter(id=installation.id).exists()

    def test_duplicate_installation_rejected_by_url(self):
        server = self._create_server()
        MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            server=server,
            display_name=server.name,
            url=server.url,
            auth_type=server.auth_type,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/",
            data={"server_id": str(server.id), "url": server.url, "display_name": server.name},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_can_install_any_platform_server(self):
        server = self._create_server(name="Platform Server", url="https://platform.example.com")

        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        response = self.client.post(
            f"/api/environments/{team2.id}/mcp_server_installations/",
            data={"server_id": str(server.id), "url": server.url, "display_name": server.name},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_user_isolation(self):
        server = self._create_server()
        MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            server=server,
            display_name=server.name,
            url=server.url,
            auth_type=server.auth_type,
        )

        from posthog.models import User

        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        other_installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=other_user,
            server=server,
            display_name=server.name,
            url=server.url,
            auth_type=server.auth_type,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/mcp_server_installations/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["id"] != str(other_installation.id)


class TestInstallCustomAPI(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def test_install_custom_api_key_server(self):
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
        assert response.json()["server"] is None
        assert not MCPServer.objects.filter(url="https://mcp.custom.com").exists()

    def test_install_custom_no_auth_server(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Open Server", "url": "https://mcp.open.com", "auth_type": "none"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["auth_type"] == "none"
        assert response.json()["server"] is None

    def test_install_custom_duplicate_url_rejected(self):
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

    def test_installation_name_field(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Custom Name", "url": "https://mcp.named.com", "auth_type": "none"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["display_name"] == "Custom Name"
        assert response.json()["name"] == "Custom Name"
