from posthog.test.base import BaseTest

from django.urls import reverse

from products.mcp_store.backend.models import MCPGatewayServer


class TestMCPGatewayServerAdmin(BaseTest):
    def test_staff_edit_the_description_without_changing_access(self) -> None:
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        server = MCPGatewayServer.objects.for_team(self.team.id).create(
            team=self.team,
            name="Slack",
            url="https://mcp.slack.example.com/mcp",
            description="Old text",
            is_team_enabled=True,
        )
        change_url = reverse("admin:mcp_store_mcpgatewayserver_change", args=[server.pk])

        assert self.client.get(reverse("admin:mcp_store_mcpgatewayserver_changelist")).status_code == 200
        response = self.client.post(
            change_url,
            {"name": "Slack", "description": "New text", "category": server.category, "is_team_enabled": ""},
        )

        assert response.status_code == 302, response.content
        server.refresh_from_db()
        assert (server.description, server.is_team_enabled) == ("New text", True)

        delete_url = reverse("admin:mcp_store_mcpgatewayserver_delete", args=[server.pk])
        assert self.client.post(delete_url, {"post": "yes"}).status_code == 403
        assert MCPGatewayServer.objects.for_team(self.team.id).filter(pk=server.pk).exists()
