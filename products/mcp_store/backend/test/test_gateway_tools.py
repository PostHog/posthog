from posthog.test.base import APIBaseTest

from django.utils import timezone

from rest_framework import status

from products.mcp_store.backend.models import MCPGatewayServer, MCPServerInstallation, MCPServerInstallationTool


class TestMCPGatewayToolPoliciesAPI(APIBaseTest):
    def test_tools_include_the_upstream_input_schema(self) -> None:
        server = MCPGatewayServer.objects.for_team(self.team.id).create(
            team=self.team,
            name="Schema server",
            url="https://mcp.schema-test.example.com/mcp",
        )
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            gateway_server=server,
            display_name="Schema server",
            url=server.url,
        )
        input_schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
        MCPServerInstallationTool.objects.create(
            installation=installation,
            tool_name="search_items",
            description="Search for matching items.",
            input_schema=input_schema,
            last_seen_at=timezone.now(),
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/mcp_gateway/servers/{server.id}/tools/",
            {"scope_type": "team"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"][0]["input_schema"] == input_schema
