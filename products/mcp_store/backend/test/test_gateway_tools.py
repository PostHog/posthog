from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import User

from products.mcp_store.backend.facade.api import resolve_member_tool_states
from products.mcp_store.backend.models import (
    MCPGatewayServer,
    MCPServerInstallation,
    MCPServerInstallationTool,
    MCPToolPolicy,
)
from products.mcp_store.backend.policy import SYNC_DEFAULT_APPROVAL_STATE, GatewayCaller, PolicyContext


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

    def _server_with_tool(self, slug: str, *, legacy_state: str) -> tuple[MCPGatewayServer, MCPServerInstallation]:
        server = MCPGatewayServer.objects.for_team(self.team.id).create(
            team=self.team,
            name=f"{slug} server",
            url=f"https://mcp.{slug}-test.example.com/mcp",
        )
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            gateway_server=server,
            display_name=f"{slug} server",
            url=server.url,
        )
        MCPServerInstallationTool.objects.create(
            installation=installation,
            tool_name="search_items",
            description="Search for matching items.",
            last_seen_at=timezone.now(),
            approval_state=legacy_state,
        )
        return server, installation

    def _member_row(self, server: MCPGatewayServer) -> dict:
        response = self.client.get(
            f"/api/projects/{self.team.id}/mcp_gateway/servers/{server.id}/tools/",
            {"scope_type": "member", "scope_user_id": str(self.user.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        return response.json()["results"][0]

    def test_synced_default_does_not_become_a_member_preference(self) -> None:
        """A tool nobody has touched must resolve the same for "You" as for the team.

        Tool sync stamps needs_approval on every new row. Treating that as the
        member's own choice made it beat the team baseline, so a fresh install
        showed Always Allow under Team Default and every agent, but Needs
        Approval for the signed-in member.
        """
        server, _ = self._server_with_tool("synced", legacy_state=SYNC_DEFAULT_APPROVAL_STATE)
        MCPToolPolicy.objects.for_team(self.team.id).create(
            team=self.team,
            gateway_server=server,
            tool_name="search_items",
            scope_type="team",
            state="approved",
        )

        team_response = self.client.get(
            f"/api/projects/{self.team.id}/mcp_gateway/servers/{server.id}/tools/",
            {"scope_type": "team"},
        )
        assert team_response.status_code == status.HTTP_200_OK

        row = self._member_row(server)
        assert row["policy_state"] == "approved"
        assert row["decided_by"] == "team"
        assert row["policy_state"] == team_response.json()["results"][0]["policy_state"]

    def test_explicit_legacy_state_is_still_a_member_preference(self) -> None:
        """Only the synced default is ignored — a real choice still applies.

        A state the sync never writes can only have come from the member, so it
        keeps beating a laxer team ceiling, and this view has to report it or
        the UI would promise access the proxy then refuses.
        """
        server, _ = self._server_with_tool("explicit", legacy_state="do_not_use")
        MCPToolPolicy.objects.for_team(self.team.id).create(
            team=self.team,
            gateway_server=server,
            tool_name="search_items",
            scope_type="team",
            state="approved",
        )

        row = self._member_row(server)
        assert row["policy_state"] == "do_not_use"
        assert row["decided_by"] == "legacy"
        # The team ceiling is still reported, so the UI can show what's available.
        assert row["team_state"] == "approved"

    def test_member_scope_row_overrides_the_legacy_state(self) -> None:
        """Choosing "Always Allow" writes a member scope row, which wins."""
        server, _ = self._server_with_tool("override", legacy_state="do_not_use")
        MCPToolPolicy.objects.for_team(self.team.id).create(
            team=self.team,
            gateway_server=server,
            tool_name="search_items",
            scope_type="team",
            state="approved",
        )
        MCPToolPolicy.objects.for_team(self.team.id).create(
            team=self.team,
            gateway_server=server,
            tool_name="search_items",
            scope_type="member",
            scope_user=self.user,
            state="approved",
        )

        row = self._member_row(server)
        assert row["policy_state"] == "approved"
        assert row["decided_by"] == "scope"

    @parameterized.expand(
        [
            (f"{entry_point}_{caller}_{legacy_state}", entry_point, caller == "owner", legacy_state, expected)
            for entry_point in ("policy_context", "facade", "facade_unlinked")
            for caller, legacy_state, expected in (
                ("owner", "approved", "approved"),
                ("teammate", "approved", "needs_approval"),
                ("teammate", "do_not_use", "do_not_use"),
            )
        ]
    )
    def test_shared_installation_teammates_keep_owner_restrictions_but_not_approvals(
        self, _name: str, entry_point: str, caller_is_owner: bool, legacy_state: str, expected: str
    ) -> None:
        server, installation = self._server_with_tool("shared", legacy_state=legacy_state)
        installation.scope = "shared"
        installation.save(update_fields=["scope"])
        caller = (
            self.user if caller_is_owner else User.objects.create_and_join(self.organization, "mate@example.com", None)
        )

        if entry_point == "policy_context":
            state = (
                PolicyContext(
                    team_id=self.team.id,
                    caller=GatewayCaller(kind="member", user_id=caller.id),
                    gateway_server=server,
                    installation=installation,
                )
                .resolve("search_items")
                .state
            )
        else:
            gateway_server_id = server.id if entry_point == "facade" else None
            state = resolve_member_tool_states(str(installation.id), self.team.id, gateway_server_id, caller.id)[
                "search_items"
            ]

        assert state == expected
