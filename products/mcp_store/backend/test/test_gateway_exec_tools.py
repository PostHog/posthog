from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.oauth import OAuthAccessToken, OAuthApplication

from products.mcp_store.backend.models import (
    MCPAuditEvent,
    MCPGatewayServer,
    MCPMemberServerRevocation,
    MCPServerInstallation,
    MCPServerInstallationTool,
)

_UPSTREAM_RESULT = {"content": [{"type": "text", "text": "done"}], "isError": False}


class TestGatewayExecTools(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.server = MCPGatewayServer.objects.for_team(self.team.id).create(
            team=self.team,
            name="Linear",
            url="https://mcp.linear.example.com/mcp",
        )
        self.installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            gateway_server=self.server,
            display_name="Linear",
            url=self.server.url,
            auth_type="api_key",
            sensitive_configuration={"api_key": "sk-test"},
        )

    def _tool(self, *, name: str = "create_issue", state: str = "approved", removed: bool = False, **kwargs):
        return MCPServerInstallationTool.objects.create(
            installation=kwargs.pop("installation", self.installation),
            tool_name=name,
            description=kwargs.pop("description", "Create an issue"),
            input_schema=kwargs.pop("input_schema", {"type": "object", "properties": {"title": {"type": "string"}}}),
            approval_state=state,
            last_seen_at=timezone.now(),
            removed_at=timezone.now() if removed else None,
            **kwargs,
        )

    def _call(self, installation_id=None, tool_name: str = "create_issue", arguments=None):
        return self.client.post(
            f"/api/projects/{self.team.id}/mcp_server_installations/{installation_id or self.installation.id}/call_tool/",
            {"tool_name": tool_name, "arguments": arguments or {"title": "Bug"}},
            format="json",
        )

    def _available(self):
        return self.client.get(f"/api/projects/{self.team.id}/mcp_server_installations/available_tools/")

    @parameterized.expand(
        [
            ("approved", "approved", False, status.HTTP_200_OK, True, "approved"),
            ("needs_approval", "needs_approval", False, status.HTTP_403_FORBIDDEN, False, "pending"),
            ("do_not_use", "do_not_use", False, status.HTTP_403_FORBIDDEN, False, "blocked"),
            ("removed_upstream", "approved", True, status.HTTP_404_NOT_FOUND, False, "blocked"),
        ]
    )
    @patch("products.mcp_store.backend.presentation.views.call_upstream_tool", return_value=_UPSTREAM_RESULT)
    def test_call_tool_enforces_policy_and_audits(
        self, _name, state, removed, expected_status, expect_upstream, expected_decision, mock_call
    ):
        self._tool(state=state, removed=removed)

        response = self._call()

        assert response.status_code == expected_status, response.json()
        assert mock_call.called is expect_upstream
        audit = MCPAuditEvent.objects.for_team(self.team.id).get(tool_name="create_issue")
        assert audit.decision == expected_decision
        assert audit.actor_user_id == self.user.id

    @patch("products.mcp_store.backend.presentation.views.call_upstream_tool", return_value=_UPSTREAM_RESULT)
    def test_call_tool_returns_upstream_text(self, mock_call):
        self._tool()

        response = self._call()

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "content": [{"type": "text", "text": "done"}],
            "is_error": False,
            "structured_content": None,
        }
        assert mock_call.call_args.args[1:] == ("create_issue", {"title": "Bug"})

    @parameterized.expand(
        [
            ("string", "not a list"),
            ("int", 42),
            ("dict", {"type": "text", "text": "done"}),
        ]
    )
    def test_call_tool_tolerates_non_list_upstream_content(self, _name, malformed_content):
        self._tool()

        with patch(
            "products.mcp_store.backend.presentation.views.call_upstream_tool",
            return_value={"content": malformed_content, "isError": False},
        ):
            response = self._call()

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["content"] == []

    @patch("products.mcp_store.backend.presentation.views.call_upstream_tool")
    def test_call_tool_rejects_unregistered_tool_without_calling_upstream(self, mock_call):
        self._tool()

        response = self._call(tool_name="delete_everything")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["reason"] == "removed"
        assert not mock_call.called
        assert not MCPAuditEvent.objects.for_team(self.team.id).exists()

    @parameterized.expand([("server_disabled_for_team",), ("member_revoked",)])
    @patch("products.mcp_store.backend.presentation.views.call_upstream_tool")
    def test_call_tool_honors_admin_kill_switches(self, scenario, mock_call):
        self._tool()
        if scenario == "server_disabled_for_team":
            self.server.is_team_enabled = False
            self.server.save()
        else:
            MCPMemberServerRevocation.objects.for_team(self.team.id).create(
                team=self.team, gateway_server=self.server, user=self.user
            )

        response = self._call()

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not mock_call.called

    def _read_scoped_token_client(self) -> APIClient:
        """A `project:read` OAuth client, which is how the PostHog MCP authenticates.
        Session auth takes a different branch through APIScopePermission, so it cannot
        catch an action that derives no scope."""
        application = OAuthApplication.objects.create(
            name="MCP gateway exec",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token="pha_mcp_gateway_exec_read",
            expires=timezone.now() + timedelta(hours=1),
            scope="project:read",
            scoped_teams=[self.team.id],
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token.token}")
        return client

    @parameterized.expand([("available_tools",), ("call_tool",)])
    @patch("products.mcp_store.backend.presentation.views.call_upstream_tool", return_value=_UPSTREAM_RESULT)
    def test_agent_surfaces_reach_both_endpoints_with_a_read_scoped_token(self, endpoint, _mock_call):
        self._tool()
        client = self._read_scoped_token_client()
        base = f"/api/projects/{self.team.id}/mcp_server_installations/"

        if endpoint == "available_tools":
            response = client.get(f"{base}available_tools/")
        else:
            response = client.post(
                f"{base}{self.installation.id}/call_tool/",
                {"tool_name": "create_issue", "arguments": {}},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_available_tools_lists_callable_tools_with_schema(self):
        self._tool()

        response = self._available()

        assert response.status_code == status.HTTP_200_OK
        servers = response.json()["servers"]
        assert len(servers) == 1
        assert servers[0]["slug"] == "linear"
        assert servers[0]["installation_id"] == str(self.installation.id)
        assert servers[0]["tools"] == [
            {
                "name": "create_issue",
                "description": "Create an issue",
                "input_schema": {"type": "object", "properties": {"title": {"type": "string"}}},
                "annotations": {},
                "approval_state": "approved",
            }
        ]

    @parameterized.expand(
        [
            ("do_not_use_tool",),
            ("removed_tool",),
            ("another_users_personal_install",),
            ("server_disabled_for_team",),
            ("member_revoked",),
            ("installation_disabled",),
            ("oauth_needs_reauth",),
        ]
    )
    def test_available_tools_omits_unreachable_tools(self, scenario):
        if scenario == "another_users_personal_install":
            other = self._create_user("someone-else@posthog.com")
            other_installation = MCPServerInstallation.objects.create(
                team=self.team,
                user=other,
                gateway_server=self.server,
                display_name="Linear",
                url="https://mcp.linear-other.example.com/mcp",
                auth_type="api_key",
                sensitive_configuration={"api_key": "sk-other"},
            )
            self._tool(installation=other_installation)
        else:
            self._tool(
                state="do_not_use" if scenario == "do_not_use_tool" else "approved",
                removed=scenario == "removed_tool",
            )

        if scenario == "server_disabled_for_team":
            self.server.is_team_enabled = False
            self.server.save()
        elif scenario == "member_revoked":
            MCPMemberServerRevocation.objects.for_team(self.team.id).create(
                team=self.team, gateway_server=self.server, user=self.user
            )
        elif scenario == "installation_disabled":
            self.installation.is_enabled = False
            self.installation.save()
        elif scenario == "oauth_needs_reauth":
            self.installation.auth_type = "oauth"
            self.installation.sensitive_configuration = {"access_token": "tok", "needs_reauth": True}
            self.installation.save()

        assert self._available().json()["servers"] == []

    def test_available_tools_includes_a_teammates_shared_connection(self):
        other = self._create_user("shared-owner@posthog.com")
        shared = MCPServerInstallation.objects.create(
            team=self.team,
            user=other,
            scope="shared",
            gateway_server=self.server,
            display_name="Linear",
            url="https://mcp.linear-shared.example.com/mcp",
            auth_type="api_key",
            sensitive_configuration={"api_key": "sk-shared"},
        )
        self._tool(installation=shared)

        servers = self._available().json()["servers"]

        assert [s["installation_id"] for s in servers] == [str(shared.id)]

    def test_available_tools_keys_colliding_slugs_to_their_installation(self):
        # Numbering same-named connections by position would reshuffle when one goes
        # unavailable, so a tool name an agent read from `search` could later resolve to a
        # different connection. Keying the suffix to the installation prevents that.
        self._tool()
        second = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            gateway_server=self.server,
            display_name="Linear",
            url="https://mcp.linear-second.example.com/mcp",
            auth_type="api_key",
            sensitive_configuration={"api_key": "sk-second"},
        )
        self._tool(installation=second)

        slugs = {s["installation_id"]: s["slug"] for s in self._available().json()["servers"]}

        assert slugs == {
            str(self.installation.id): f"linear--{self.installation.id.hex[-6:]}",
            str(second.id): f"linear--{second.id.hex[-6:]}",
        }

        # The surviving connection keeps the slug it already had once its twin drops out.
        second.is_enabled = False
        second.save()

        remaining = self._available().json()["servers"]
        assert [s["slug"] for s in remaining] == [f"linear--{self.installation.id.hex[-6:]}"]

    def test_available_tools_crafted_name_cannot_collide_with_a_generated_slug(self):
        # A second `linear` install forces both onto `linear--<hex>` slugs. A third
        # connection named to match one of those generated slugs (its single-dash form,
        # the only shape a display name can normalize to) must not reuse it — a colliding
        # slug would let exec (first match wins) route a call to the wrong server. The
        # `--` separator keeps a display name from ever producing a generated slug.
        self._tool()
        second = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            gateway_server=self.server,
            display_name="Linear",
            url="https://mcp.linear-second.example.com/mcp",
            auth_type="api_key",
            sensitive_configuration={"api_key": "sk-second"},
        )
        self._tool(installation=second)
        crafted = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            gateway_server=self.server,
            display_name=f"linear-{self.installation.id.hex[-6:]}",
            url="https://mcp.linear-crafted.example.com/mcp",
            auth_type="api_key",
            sensitive_configuration={"api_key": "sk-crafted"},
        )
        self._tool(installation=crafted)

        slugs = [s["slug"] for s in self._available().json()["servers"]]

        assert len(slugs) == len(set(slugs)), f"slugs must be unique, got {slugs}"
