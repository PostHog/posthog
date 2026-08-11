from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.organization import OrganizationMembership

from products.mcp_store.backend.models import MCPAuditEvent, MCPGatewayServer, MCPServerInstallation, MCPServiceAccount


class TestMCPGatewayAuditAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        membership = self.user.organization_memberships.get(organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

        other_user = self._create_user("other-audit-member@posthog.com")
        server = MCPGatewayServer.objects.for_team(self.team.id).create(
            team=self.team,
            name="Audit server",
            url="https://mcp.audit-visibility.example.com/mcp",
        )
        own_installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            gateway_server=server,
            display_name=server.name,
            url=server.url,
            auth_type="api_key",
        )
        other_installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=other_user,
            gateway_server=server,
            display_name=server.name,
            url=server.url,
            auth_type="api_key",
        )
        agent = MCPServiceAccount.objects.for_team(self.team.id).create(
            team=self.team,
            name="Support agent",
            handle="support-agent",
            token_hash="audit-visibility-support-agent",
        )

        self.member_event = MCPAuditEvent.objects.for_team(self.team.id).create(
            team=self.team,
            gateway_server=server,
            installation=own_installation,
            actor_user=self.user,
            actor_label=self.user.email,
            server_name=server.name,
            tool_name="member_tool",
            decision="blocked",
        )
        self.agent_event = MCPAuditEvent.objects.for_team(self.team.id).create(
            team=self.team,
            gateway_server=server,
            installation=own_installation,
            actor_service_account=agent,
            actor_label=agent.handle,
            server_name=server.name,
            tool_name="agent_tool",
            decision="approved",
        )
        self.other_member_event = MCPAuditEvent.objects.for_team(self.team.id).create(
            team=self.team,
            gateway_server=server,
            installation=other_installation,
            actor_user=other_user,
            actor_label=other_user.email,
            server_name=server.name,
            tool_name="other_member_tool",
            decision="pending",
        )

    def _api_url(self, suffix: str = "") -> str:
        base = f"/api/projects/{self.team.id}/mcp_gateway/audit/"
        return f"{base}{suffix}" if suffix else base

    def test_member_sees_only_calls_using_their_connections(self) -> None:
        list_response = self.client.get(self._api_url())
        counts_response = self.client.get(self._api_url("counts/"))
        own_detail_response = self.client.get(self._api_url(f"{self.agent_event.id}/"))
        other_detail_response = self.client.get(self._api_url(f"{self.other_member_event.id}/"))

        assert list_response.status_code == status.HTTP_200_OK
        assert {event["id"] for event in list_response.json()["results"]} == {
            str(self.member_event.id),
            str(self.agent_event.id),
        }
        assert counts_response.status_code == status.HTTP_200_OK
        assert counts_response.json() == {"all": 2, "agents": 1, "approvals": 1, "blocked": 1}
        assert own_detail_response.status_code == status.HTTP_200_OK
        assert other_detail_response.status_code == status.HTTP_404_NOT_FOUND

    def test_counts_scope_to_service_account_filter(self) -> None:
        account_id = str(self.agent_event.actor_service_account_id)
        counts_response = self.client.get(self._api_url("counts/"), {"actor_service_account_id": account_id})

        assert counts_response.status_code == status.HTTP_200_OK
        assert counts_response.json() == {"all": 1, "agents": 1, "approvals": 1, "blocked": 0}

    def test_admin_still_sees_all_team_calls(self) -> None:
        membership = self.user.organization_memberships.get(organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

        list_response = self.client.get(self._api_url())
        counts_response = self.client.get(self._api_url("counts/"))
        other_detail_response = self.client.get(self._api_url(f"{self.other_member_event.id}/"))

        assert list_response.status_code == status.HTTP_200_OK
        assert {event["id"] for event in list_response.json()["results"]} == {
            str(self.member_event.id),
            str(self.agent_event.id),
            str(self.other_member_event.id),
        }
        assert counts_response.status_code == status.HTTP_200_OK
        assert counts_response.json() == {"all": 3, "agents": 1, "approvals": 2, "blocked": 1}
        assert other_detail_response.status_code == status.HTTP_200_OK
