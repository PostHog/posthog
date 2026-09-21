from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import User

from products.mcp_store.backend.gateway import installation_for_agent_access
from products.mcp_store.backend.models import (
    MCPGatewayServer,
    MCPServerInstallation,
    MCPServiceAccount,
    MCPServiceAccountServerAccess,
)


class TestInstallationForAgentAccess(BaseTest):
    @parameterized.expand([("same_owner", True), ("other_member", False)])
    def test_resolves_only_a_credential_owned_by_the_granting_member(
        self, _name: str, installation_owned_by_granter: bool
    ) -> None:
        teammate = User.objects.create_and_join(self.organization, "teammate-credential@posthog.com", "password")
        server = MCPGatewayServer.objects.for_team(self.team.id).create(
            team=self.team,
            name="Notion",
            url="https://mcp.agent-access.example.com/mcp",
        )
        installation_owner = self.user if installation_owned_by_granter else teammate
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=installation_owner,
            display_name=server.name,
            url=server.url,
            auth_type="api_key",
            sensitive_configuration={"api_key": "secret"},
            scope="personal",
            gateway_server=server,
        )
        account = MCPServiceAccount.objects.for_team(self.team.id).create(
            team=self.team,
            name="Scout",
            handle="posthog-scout",
            token_hash="agent-access-token-hash",
        )
        access = MCPServiceAccountServerAccess.objects.for_team(self.team.id).create(
            team=self.team,
            user=self.user,
            service_account=account,
            gateway_server=server,
            installation=installation,
            granted_by=self.user,
        )

        resolved = installation_for_agent_access(access)

        assert resolved == (installation if installation_owned_by_granter else None)
