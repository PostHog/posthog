from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models import User

from products.mcp_store.backend.agents import BUILT_IN_AGENTS, sync_built_in_agents
from products.mcp_store.backend.models import (
    MCPGatewayServer,
    MCPServerInstallation,
    MCPServiceAccount,
    MCPServiceAccountServerAccess,
)


class TestSyncBuiltInAgents(BaseTest):
    def _server(self, name: str) -> MCPGatewayServer:
        return MCPGatewayServer.objects.for_team(self.team.id).create(
            team_id=self.team.id, name=name, url=f"https://{name.lower()}.example.com/mcp", is_team_enabled=True
        )

    def _installation(self, server: MCPGatewayServer, user: User) -> MCPServerInstallation:
        return MCPServerInstallation.objects.create(
            team=self.team,
            user=user,
            display_name=server.name,
            url=server.url,
            auth_type="api_key",
            is_enabled=True,
            scope="personal",
            gateway_server=server,
        )

    def _grant(
        self,
        account: MCPServiceAccount,
        server: MCPGatewayServer,
        *,
        user: User | None,
        installation: MCPServerInstallation | None,
        scope: str = "personal",
    ) -> None:
        MCPServiceAccountServerAccess.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            service_account=account,
            gateway_server=server,
            user=user,
            installation=installation,
            granted_by=user,
            scope=scope,
        )

    def test_an_agent_added_to_the_catalog_inherits_the_grants_its_siblings_hold(self) -> None:
        # The team connected servers while only the first two agents existed.
        with patch("products.mcp_store.backend.agents.BUILT_IN_AGENTS", BUILT_IN_AGENTS[:2]):
            support, scout = sync_built_in_agents(self.team)
        teammate = User.objects.create_and_join(self.organization, "teammate@posthog.com", "password")
        team_server = self._server("Team")
        own_server = self._server("Own")
        legacy_server = self._server("Legacy")
        team_shared = self._installation(team_server, teammate)
        own = self._installation(own_server, self.user)
        # The same member shared one server personally with one agent and team-wide with another.
        self._grant(support, team_server, user=teammate, installation=team_shared)
        self._grant(scout, team_server, user=teammate, installation=team_shared, scope="team")
        self._grant(scout, own_server, user=self.user, installation=own)
        # A user-less row from a previous release resolves for nobody, so it is not copied.
        self._grant(support, legacy_server, user=None, installation=None)

        accounts = sync_built_in_agents(self.team)
        sync_built_in_agents(self.team)

        workflow = accounts[2]
        assert workflow.handle == "posthog-workflow"
        rows = MCPServiceAccountServerAccess.objects.for_team(self.team.id).filter(service_account=workflow)
        assert set(rows.values_list("gateway_server_id", "user_id", "scope", "installation_id")) == {
            (team_server.id, teammate.id, "team", team_shared.id),
            (own_server.id, self.user.id, "personal", own.id),
        }
        # Existing agents keep their own grants; a second sync neither duplicates nor resets.
        assert rows.count() == 2
        assert MCPServiceAccountServerAccess.objects.for_team(self.team.id).filter(service_account=support).count() == 2
