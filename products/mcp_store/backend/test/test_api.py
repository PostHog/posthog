from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest

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
            data={"server_id": str(server.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["server"]["id"] == str(server.id)
        assert response.json()["server"]["name"] == "Test Server"

    def test_list_installations(self):
        server = self._create_server()
        MCPServerInstallation.objects.create(team=self.team, user=self.user, server=server)

        response = self.client.get(f"/api/environments/{self.team.id}/mcp_server_installations/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1

    def test_uninstall_server(self):
        server = self._create_server()
        installation = MCPServerInstallation.objects.create(team=self.team, user=self.user, server=server)

        response = self.client.delete(f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not MCPServerInstallation.objects.filter(id=installation.id).exists()

    def test_duplicate_installation_rejected(self):
        server = self._create_server()
        MCPServerInstallation.objects.create(team=self.team, user=self.user, server=server)

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/",
            data={"server_id": str(server.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_can_install_any_platform_server(self):
        server = self._create_server(name="Platform Server", url="https://platform.example.com")

        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        response = self.client.post(
            f"/api/environments/{team2.id}/mcp_server_installations/",
            data={"server_id": str(server.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_user_isolation(self):
        server = self._create_server()
        MCPServerInstallation.objects.create(team=self.team, user=self.user, server=server)

        from posthog.models import User

        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        other_installation = MCPServerInstallation.objects.create(team=self.team, user=other_user, server=server)

        response = self.client.get(f"/api/environments/{self.team.id}/mcp_server_installations/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["id"] != str(other_installation.id)
