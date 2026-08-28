from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import User
from posthog.models.organization import OrganizationMembership

from products.mcp_store.backend.agents import (
    create_gateway_agent_token,
    get_built_in_agent,
    resolve_gateway_agent_token,
)
from products.mcp_store.backend.facade.api import (
    get_active_installations,
    get_installations_for_sandbox,
    get_sandbox_mcp_server_names,
)
from products.mcp_store.backend.facade.contracts import ActiveInstallation
from products.mcp_store.backend.models import (
    MCPGatewayServer,
    MCPMemberServerRevocation,
    MCPServerInstallation,
    MCPServerTemplate,
    MCPServiceAccount,
    MCPServiceAccountServerAccess,
)


class TestGetActiveInstallations(BaseTest):
    def _create_installation(self, **kwargs) -> MCPServerInstallation:
        defaults: dict = {
            "team": self.team,
            "user": self.user,
            "display_name": "Linear",
            "url": "https://mcp.linear.app/mcp",
            "auth_type": "api_key",
            "is_enabled": True,
        }
        defaults.update(kwargs)
        return MCPServerInstallation.objects.create(**defaults)

    def test_returns_active_installations(self) -> None:
        installation = self._create_installation()

        results = get_active_installations(self.team.id, self.user.id)

        assert results == [
            ActiveInstallation(
                id=str(installation.id),
                name="Linear",
                proxy_path=f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/proxy/",
                scope="personal",
            )
        ]

    def test_skips_disabled_installations(self) -> None:
        self._create_installation(is_enabled=False)

        assert get_active_installations(self.team.id, self.user.id) == []

    def test_skips_oauth_needing_reauth(self) -> None:
        self._create_installation(
            auth_type="oauth",
            sensitive_configuration={"needs_reauth": True, "access_token": "tok"},
        )

        assert get_active_installations(self.team.id, self.user.id) == []

    def test_skips_oauth_pending_token(self) -> None:
        self._create_installation(auth_type="oauth", sensitive_configuration={})

        assert get_active_installations(self.team.id, self.user.id) == []

    def test_includes_oauth_with_valid_token(self) -> None:
        self._create_installation(
            auth_type="oauth",
            sensitive_configuration={"access_token": "tok"},
        )

        assert len(get_active_installations(self.team.id, self.user.id)) == 1

    def test_api_key_not_filtered_by_oauth_checks(self) -> None:
        self._create_installation(auth_type="api_key", sensitive_configuration={})

        assert len(get_active_installations(self.team.id, self.user.id)) == 1

    def test_uses_display_name(self) -> None:
        self._create_installation(display_name="My Custom Server")

        results = get_active_installations(self.team.id, self.user.id)

        assert results[0].name == "My Custom Server"

    def test_name_falls_back_to_template_name(self) -> None:
        template = MCPServerTemplate.objects.create(
            name="Custom Template",
            url="https://mcp.custom-template.example.com/mcp",
            auth_type="oauth",
            created_by=self.user,
        )
        self._create_installation(display_name="", template=template, url=template.url)

        results = get_active_installations(self.team.id, self.user.id)

        assert results[0].name == "Custom Template"

    def test_name_falls_back_to_url(self) -> None:
        self._create_installation(display_name="", url="https://mcp.notion.com/mcp")

        results = get_active_installations(self.team.id, self.user.id)

        assert results[0].name == "https://mcp.notion.com/mcp"

    def test_returns_description_for_agent_discovery(self) -> None:
        # Agents match a never-connected MCP server on this text alone, so an empty
        # description leaves the server findable only by its exact name.
        self._create_installation(description="Manage Linear issues, projects, teams, and workflows.")

        results = get_active_installations(self.team.id, self.user.id)

        assert results[0].description == "Manage Linear issues, projects, teams, and workflows."

    def test_description_falls_back_to_template(self) -> None:
        template = MCPServerTemplate.objects.create(
            name="Described Template",
            url="https://mcp.described-template.example.com/mcp",
            description="Search and edit pages and databases.",
            auth_type="oauth",
            created_by=self.user,
        )
        self._create_installation(description="", template=template, url=template.url)

        results = get_active_installations(self.team.id, self.user.id)

        assert results[0].description == "Search and edit pages and databases."

    def test_only_returns_for_given_user(self) -> None:
        from posthog.models import User

        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        self._create_installation(user=other_user)
        self._create_installation(url="https://mcp.other.com/mcp")

        results = get_active_installations(self.team.id, self.user.id)

        assert len(results) == 1
        assert results[0].name == "Linear"

    def test_only_returns_for_given_team(self) -> None:
        from posthog.models import Organization, Team

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        self._create_installation(team=other_team)
        self._create_installation(url="https://mcp.other.com/mcp")

        results = get_active_installations(self.team.id, self.user.id)

        assert len(results) == 1

    def test_excludes_shared_installations(self) -> None:
        self._create_installation(scope="shared")

        results = get_active_installations(self.team.id, self.user.id)

        assert len(results) == 0

    def test_include_shared_adds_team_shared_but_not_teammates_personal(self) -> None:
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        own_personal = self._create_installation()
        shared = self._create_installation(scope="shared", user=other_user, url="https://mcp.shared.com/mcp")
        self._create_installation(user=other_user, url="https://mcp.theirs.com/mcp")

        results = get_active_installations(self.team.id, self.user.id, include_shared=True)

        assert {result.id for result in results} == {str(own_personal.id), str(shared.id)}

    def test_include_shared_still_applies_readiness_checks(self) -> None:
        self._create_installation(scope="shared", is_enabled=False)
        self._create_installation(
            scope="shared",
            url="https://mcp.pending.com/mcp",
            auth_type="oauth",
            sensitive_configuration={},
        )

        assert get_active_installations(self.team.id, self.user.id, include_shared=True) == []

    @parameterized.expand(
        [
            ("enabled_api_key", True, "api_key", {}, True),
            ("disabled_api_key", False, "api_key", {}, False),
            ("oauth_with_token", True, "oauth", {"access_token": "tok"}, True),
            ("oauth_needs_reauth", True, "oauth", {"needs_reauth": True, "access_token": "tok"}, False),
            ("oauth_pending", True, "oauth", {}, False),
        ]
    )
    def test_filtering_matrix(self, _name, is_enabled, auth_type, sensitive_configuration, expected_included) -> None:
        self._create_installation(
            is_enabled=is_enabled,
            auth_type=auth_type,
            sensitive_configuration=sensitive_configuration,
        )

        results = get_active_installations(self.team.id, self.user.id)

        assert (len(results) == 1) == expected_included


class TestGetInstallationsForSandbox(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch("products.mcp_store.backend.facade.api.is_builtin_agent_enforcement_enabled", return_value=True)
        self.enforcement_enabled_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def _create_installation(self, **kwargs) -> MCPServerInstallation:
        defaults: dict = {
            "team": self.team,
            "user": self.user,
            "display_name": "Server",
            "url": "https://mcp.example.com/mcp",
            "auth_type": "api_key",
            "is_enabled": True,
            "scope": "personal",
        }
        defaults.update(kwargs)
        return MCPServerInstallation.objects.create(**defaults)

    def _create_gateway_server(self, *, name: str, url: str, is_team_enabled: bool = True) -> MCPGatewayServer:
        return MCPGatewayServer.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            name=name,
            url=url,
            is_team_enabled=is_team_enabled,
        )

    def _support_agent(self) -> MCPServiceAccount:
        account = get_built_in_agent(self.team.id, "support")
        assert account is not None
        return account

    def test_shared_always_returned(self) -> None:
        shared = self._create_installation(scope="shared", display_name="Shared Server")

        results = get_installations_for_sandbox(self.team.id)

        assert len(results) == 1
        assert results[0].id == str(shared.id)
        assert results[0].scope == "shared"

    def test_returns_description_for_agent_discovery(self) -> None:
        # A sandbox agent searches its MCP servers by capability before connecting to any of
        # them, and this text is all it has to match against.
        self._create_installation(scope="shared", description="Manage Linear issues, projects, and workflows.")

        results = get_installations_for_sandbox(self.team.id)

        assert results[0].description == "Manage Linear issues, projects, and workflows."

    def test_personal_excluded_by_default(self) -> None:
        self._create_installation(scope="personal")

        results = get_installations_for_sandbox(self.team.id)

        assert len(results) == 0

    def test_personal_included_when_requested(self) -> None:
        personal = self._create_installation(scope="personal")

        results = get_installations_for_sandbox(self.team.id, user_id=self.user.id, include_personal=True)

        assert len(results) == 1
        assert results[0].id == str(personal.id)
        assert results[0].scope == "personal"

    def test_shared_plus_personal_combined(self) -> None:
        self._create_installation(scope="shared", url="https://shared.example.com/mcp", display_name="Shared")
        self._create_installation(scope="personal", url="https://personal.example.com/mcp", display_name="Personal")

        results = get_installations_for_sandbox(self.team.id, user_id=self.user.id, include_personal=True)

        assert len(results) == 2
        scopes = {r.scope for r in results}
        assert scopes == {"shared", "personal"}

    def test_shared_visible_to_any_team_member(self) -> None:
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        self._create_installation(scope="shared", user=other_user, display_name="Other's Shared")

        results = get_installations_for_sandbox(self.team.id, user_id=self.user.id)

        assert len(results) == 1

    @parameterized.expand([("unstamped", None), ("stamped", "support")])
    def test_agent_origin_resolves_legacy_until_gateway_flag_rollout(
        self, _name: str, task_agent_key: str | None
    ) -> None:
        self.enforcement_enabled_mock.return_value = False
        shared = self._create_installation(scope="shared", display_name="Shared")
        personal = self._create_installation(
            scope="personal", url="https://personal.example.com/mcp", display_name="Personal"
        )

        results = get_installations_for_sandbox(
            self.team.id,
            user_id=self.user.id,
            include_personal=True,
            task_origin="support_reply",
            task_agent_key=task_agent_key,
        )

        assert {result.id for result in results} == {str(shared.id), str(personal.id)}
        assert all(result.proxy_token is None for result in results)

    def test_built_in_agent_only_gets_its_explicitly_delegated_credential(self) -> None:
        account = self._support_agent()
        granted_server = self._create_gateway_server(
            name="Granted",
            url="https://granted.example.com/mcp",
        )
        ungranted_server = self._create_gateway_server(
            name="Ungranted",
            url="https://ungranted.example.com/mcp",
        )
        self._create_installation(
            scope="shared",
            gateway_server=granted_server,
            url=granted_server.url,
            display_name="Granted",
        )
        personal = self._create_installation(
            scope="personal",
            gateway_server=granted_server,
            url=granted_server.url,
            display_name="Personal",
        )
        self._create_installation(
            scope="shared",
            gateway_server=ungranted_server,
            url=ungranted_server.url,
            display_name="Ungranted",
        )
        MCPServiceAccountServerAccess.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user=self.user,
            service_account=account,
            gateway_server=granted_server,
            installation=personal,
            granted_by=self.user,
        )

        results = get_installations_for_sandbox(
            self.team.id,
            user_id=self.user.id,
            include_personal=True,
            task_origin="support_reply",
            task_agent_key="support",
            credential_owner_id=self.user.id,
        )

        assert [result.id for result in results] == [str(personal.id)]
        assert (
            results[0].proxy_path
            == f"/api/mcp_store/gateway/servers/{granted_server.id}/proxy/?credential_owner={self.user.id}"
        )
        assert results[0].proxy_token is not None
        assert results[0].proxy_token.startswith("mcp_gw_")

        account.status = "paused"
        account.save(update_fields=["status"])
        assert (
            get_installations_for_sandbox(
                self.team.id,
                task_origin="support_reply",
                task_agent_key="support",
                credential_owner_id=self.user.id,
            )
            == []
        )

        account.status = "active"
        account.save(update_fields=["status"])

        unstamped_results = get_installations_for_sandbox(
            self.team.id,
            user_id=self.user.id,
            include_personal=True,
            task_origin="support_reply",
            credential_owner_id=self.user.id,
        )
        assert unstamped_results == []

        mismatched_results = get_installations_for_sandbox(
            self.team.id,
            user_id=self.user.id,
            include_personal=True,
            task_origin="support_reply",
            task_agent_key="scout",
            credential_owner_id=self.user.id,
        )
        assert mismatched_results == []

    def test_built_in_agent_only_gets_the_run_credential_owner_s_grants(self) -> None:
        account = self._support_agent()
        other_user = User.objects.create_and_join(self.organization, "other-owner@posthog.com", "password")
        server = self._create_gateway_server(name="Granted", url="https://granted.example.com/mcp")
        delegated = self._create_installation(scope="personal", gateway_server=server, url=server.url)
        MCPServiceAccountServerAccess.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user=self.user,
            service_account=account,
            gateway_server=server,
            installation=delegated,
            granted_by=self.user,
        )

        def resolve(credential_owner_id: int | None) -> list[ActiveInstallation]:
            return get_installations_for_sandbox(
                self.team.id,
                task_origin="support_reply",
                task_agent_key="support",
                credential_owner_id=credential_owner_id,
            )

        owned = resolve(self.user.id)
        assert [result.id for result in owned] == [str(delegated.id)]
        assert resolve(other_user.id) == []
        assert resolve(None) == []

        # The proxy token must name the same owner the grants were resolved under, or the
        # gateway would serve the run under a different person's credentials.
        principal = resolve_gateway_agent_token(owned[0].proxy_token or "")
        assert principal is not None
        assert principal.credential_owner_id == self.user.id

    @parameterized.expand([("deactivated",), ("removed_from_org",)])
    def test_built_in_agent_mounts_nothing_once_credential_owner_loses_eligibility(self, revocation: str) -> None:
        account = self._support_agent()
        server = self._create_gateway_server(name="Granted", url="https://granted.example.com/mcp")
        delegated = self._create_installation(scope="personal", gateway_server=server, url=server.url)
        MCPServiceAccountServerAccess.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user=self.user,
            service_account=account,
            gateway_server=server,
            installation=delegated,
            granted_by=self.user,
        )

        def resolve() -> list[ActiveInstallation]:
            return get_installations_for_sandbox(
                self.team.id,
                task_origin="support_reply",
                task_agent_key="support",
                credential_owner_id=self.user.id,
            )

        assert [result.id for result in resolve()] == [str(delegated.id)]

        if revocation == "deactivated":
            User.objects.filter(id=self.user.id).update(is_active=False)
        else:
            OrganizationMembership.objects.filter(user=self.user, organization=self.organization).delete()

        assert resolve() == []

    def test_agent_token_stops_resolving_once_credential_owner_loses_eligibility(self) -> None:
        account = self._support_agent()
        token = create_gateway_agent_token(account, credential_owner_id=self.user.id)
        assert resolve_gateway_agent_token(token) is not None

        User.objects.filter(id=self.user.id).update(is_active=False)

        assert resolve_gateway_agent_token(token) is None

    def _grant(
        self,
        account: MCPServiceAccount,
        server: MCPGatewayServer,
        *,
        user: User | None,
        installation: MCPServerInstallation,
        scope: str = "personal",
    ) -> MCPServiceAccountServerAccess:
        return MCPServiceAccountServerAccess.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user=user,
            service_account=account,
            gateway_server=server,
            installation=installation,
            granted_by=user,
            scope=scope,
        )

    def _agent_results(self, credential_owner_id: int | None) -> list[ActiveInstallation]:
        return get_installations_for_sandbox(
            self.team.id,
            task_origin="support_reply",
            task_agent_key="support",
            credential_owner_id=credential_owner_id,
        )

    def test_agent_run_mounts_its_owners_grants_plus_teammates_team_shares(self) -> None:
        account = self._support_agent()
        teammate = User.objects.create_and_join(self.organization, "teammate@posthog.com", "password")
        own_server = self._create_gateway_server(name="Own", url="https://own.example.com/mcp")
        team_server = self._create_gateway_server(name="Team", url="https://team.example.com/mcp")
        private_server = self._create_gateway_server(name="Private", url="https://private.example.com/mcp")
        own = self._create_installation(gateway_server=own_server, url=own_server.url)
        team_shared = self._create_installation(user=teammate, gateway_server=team_server, url=team_server.url)
        teammate_private = self._create_installation(
            user=teammate, gateway_server=private_server, url=private_server.url
        )
        self._grant(account, own_server, user=self.user, installation=own)
        self._grant(account, team_server, user=teammate, installation=team_shared, scope="team")
        self._grant(account, private_server, user=teammate, installation=teammate_private)

        results = self._agent_results(self.user.id)

        assert {result.id for result in results} == {str(own.id), str(team_shared.id)}

    def test_agent_run_without_a_credential_owner_mounts_only_team_shares(self) -> None:
        account = self._support_agent()
        team_server = self._create_gateway_server(name="Team", url="https://team.example.com/mcp")
        personal_server = self._create_gateway_server(name="Personal", url="https://personal.example.com/mcp")
        team_shared = self._create_installation(gateway_server=team_server, url=team_server.url)
        personal = self._create_installation(gateway_server=personal_server, url=personal_server.url)
        self._grant(account, team_server, user=self.user, installation=team_shared, scope="team")
        self._grant(account, personal_server, user=self.user, installation=personal)

        results = self._agent_results(None)

        assert [result.id for result in results] == [str(team_shared.id)]
        principal = resolve_gateway_agent_token(results[0].proxy_token or "")
        assert principal is not None
        assert principal.credential_owner_id is None

    def test_per_scout_allowlist_gates_grants_of_every_scope(self) -> None:
        account = self._support_agent()
        teammate = User.objects.create_and_join(self.organization, "teammate@posthog.com", "password")
        picked_server = self._create_gateway_server(name="Picked", url="https://picked.example.com/mcp")
        dropped_server = self._create_gateway_server(name="Dropped", url="https://dropped.example.com/mcp")
        picked = self._create_installation(user=teammate, gateway_server=picked_server, url=picked_server.url)
        dropped = self._create_installation(user=teammate, gateway_server=dropped_server, url=dropped_server.url)
        self._grant(account, picked_server, user=teammate, installation=picked, scope="team")
        self._grant(account, dropped_server, user=teammate, installation=dropped, scope="team")

        def resolve(allowed: list[str] | None) -> set[str]:
            # No credential owner, like a scout run: only team shares are reachable, and the
            # allowlist picks which of them mount.
            return {
                result.id
                for result in get_installations_for_sandbox(
                    self.team.id,
                    task_origin="support_reply",
                    task_agent_key="support",
                    allowed_gateway_server_ids=allowed,
                )
            }

        assert resolve([str(picked_server.id)]) == {str(picked.id)}
        # An empty selection mounts nothing at all: team shares are gated too, so a scout
        # with no servers selected runs without MCP servers.
        assert resolve([]) == set()
        assert resolve(None) == {str(picked.id), str(dropped.id)}

    def test_sandbox_server_names_match_what_the_sandbox_mounts(self) -> None:
        # The names projection backs prompt steering (a scout's run prompt names its mounted
        # servers before launch). If it drifts from the mount resolution — a reimplementation
        # with its own query that skips the allowlist or grant filtering — the prompt names
        # servers the sandbox doesn't hold.
        account = self._support_agent()
        teammate = User.objects.create_and_join(self.organization, "teammate@posthog.com", "password")
        picked_server = self._create_gateway_server(name="Picked", url="https://picked.example.com/mcp")
        dropped_server = self._create_gateway_server(name="Dropped", url="https://dropped.example.com/mcp")
        picked = self._create_installation(
            user=teammate, gateway_server=picked_server, url=picked_server.url, display_name="Linear"
        )
        dropped = self._create_installation(
            user=teammate, gateway_server=dropped_server, url=dropped_server.url, display_name="Notion"
        )
        self._grant(account, picked_server, user=teammate, installation=picked, scope="team")
        self._grant(account, dropped_server, user=teammate, installation=dropped, scope="team")

        names = get_sandbox_mcp_server_names(
            self.team.id,
            task_origin="support_reply",
            task_agent_key="support",
            allowed_gateway_server_ids=[str(picked_server.id)],
        )

        assert names == ["Linear"]

    def test_per_scout_allowlist_gates_a_credential_owners_personal_grant_too(self) -> None:
        account = self._support_agent()
        server = self._create_gateway_server(name="Owned", url="https://owned.example.com/mcp")
        other_server = self._create_gateway_server(name="Other", url="https://other.example.com/mcp")
        owned = self._create_installation(gateway_server=server, url=server.url)
        self._grant(account, server, user=self.user, installation=owned)

        results = get_installations_for_sandbox(
            self.team.id,
            task_origin="support_reply",
            task_agent_key="support",
            credential_owner_id=self.user.id,
            allowed_gateway_server_ids=[str(other_server.id)],
        )

        assert results == []

    def test_owner_credential_wins_over_a_teammates_team_share_of_the_same_server(self) -> None:
        account = self._support_agent()
        teammate = User.objects.create_and_join(self.organization, "teammate@posthog.com", "password")
        server = self._create_gateway_server(name="Shared server", url="https://shared.example.com/mcp")
        own = self._create_installation(gateway_server=server, url=server.url)
        teammate_installation = self._create_installation(user=teammate, gateway_server=server, url=server.url)
        self._grant(account, server, user=self.user, installation=own)
        self._grant(account, server, user=teammate, installation=teammate_installation, scope="team")

        results = self._agent_results(self.user.id)

        assert [result.id for result in results] == [str(own.id)]

    def test_every_team_share_of_one_server_mounts_under_its_owners_id(self) -> None:
        account = self._support_agent()
        teammate = User.objects.create_and_join(self.organization, "teammate@posthog.com", "password")
        server = self._create_gateway_server(name="Shared server", url="https://shared.example.com/mcp")
        mine = self._create_installation(gateway_server=server, url=server.url, display_name="Notion")
        theirs = self._create_installation(user=teammate, gateway_server=server, url=server.url, display_name="Notion")
        self._grant(account, server, user=self.user, installation=mine, scope="team")
        self._grant(account, server, user=teammate, installation=theirs, scope="team")

        results = self._agent_results(None)

        assert {result.id for result in results} == {str(mine.id), str(theirs.id)}
        # Sandboxes key servers by name and the gateway resolves a credential from the
        # proxy path, so both have to be unique per mounted grant.
        assert {result.name for result in results} == {
            f"Notion (#{self.user.id})",
            f"Notion (#{teammate.id})",
        }
        assert {result.proxy_path for result in results} == {
            f"/api/mcp_store/gateway/servers/{server.id}/proxy/?credential_owner={self.user.id}",
            f"/api/mcp_store/gateway/servers/{server.id}/proxy/?credential_owner={teammate.id}",
        }

    @parameterized.expand(
        [
            ("credential_deleted", "deleted"),
            ("oauth_needs_reauth", "unready_oauth"),
            ("installation_disabled", "disabled"),
        ]
    )
    def test_broken_own_grant_does_not_suppress_a_working_team_share(self, _name: str, breakage: str) -> None:
        account = self._support_agent()
        teammate = User.objects.create_and_join(self.organization, "teammate@posthog.com", "password")
        server = self._create_gateway_server(name="Shared server", url="https://shared.example.com/mcp")
        own_kwargs: dict = {"gateway_server": server, "url": server.url}
        if breakage == "unready_oauth":
            own_kwargs |= {"auth_type": "oauth", "sensitive_configuration": {"needs_reauth": True}}
        if breakage == "disabled":
            own_kwargs |= {"is_enabled": False}
        own = self._create_installation(**own_kwargs)
        teammate_installation = self._create_installation(user=teammate, gateway_server=server, url=server.url)
        own_grant = self._grant(account, server, user=self.user, installation=own)
        self._grant(account, server, user=teammate, installation=teammate_installation, scope="team")
        if breakage == "deleted":
            own.delete()
            own_grant.refresh_from_db()
            assert own_grant.installation_id is None

        results = self._agent_results(self.user.id)

        assert [result.id for result in results] == [str(teammate_installation.id)]

    @parameterized.expand([("nobodys_run", False), ("owners_own_run", True)])
    def test_revoked_members_team_share_is_not_mounted(self, _name: str, run_has_owner: bool) -> None:
        account = self._support_agent()
        server = self._create_gateway_server(name="Revoked", url="https://revoked.example.com/mcp")
        installation = self._create_installation(gateway_server=server, url=server.url)
        self._grant(account, server, user=self.user, installation=installation, scope="team")
        admin = User.objects.create_and_join(self.organization, "revoking-admin@posthog.com", "password")
        MCPMemberServerRevocation.objects.for_team(self.team.id).create(
            team_id=self.team.id, gateway_server=server, user=self.user, revoked_by=admin
        )

        assert self._agent_results(self.user.id if run_has_owner else None) == []

    def test_team_scoped_grant_without_a_user_is_never_mounted(self) -> None:
        account = self._support_agent()
        server = self._create_gateway_server(name="Orphaned", url="https://orphaned.example.com/mcp")
        installation = self._create_installation(gateway_server=server, url=server.url)
        self._grant(account, server, user=None, installation=installation, scope="team")

        assert self._agent_results(None) == []
        assert self._agent_results(self.user.id) == []

    def test_built_in_agent_does_not_fall_back_after_delegated_credential_is_deleted(self) -> None:
        account = self._support_agent()
        server = self._create_gateway_server(
            name="Delegated",
            url="https://delegated.example.com/mcp",
        )
        self._create_installation(
            scope="shared",
            gateway_server=server,
            url=server.url,
            display_name="Shared",
        )
        delegated = self._create_installation(
            scope="personal",
            gateway_server=server,
            url=server.url,
            display_name="Delegated",
        )
        access = MCPServiceAccountServerAccess.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user=self.user,
            service_account=account,
            gateway_server=server,
            installation=delegated,
            granted_by=self.user,
        )

        delegated.delete()

        access.refresh_from_db()
        assert access.installation_id is None
        assert (
            get_installations_for_sandbox(
                self.team.id,
                task_origin="support_reply",
                task_agent_key="support",
                credential_owner_id=self.user.id,
            )
            == []
        )

    def test_built_in_agent_blocked_when_admin_disables_server_for_team(self) -> None:
        account = self._support_agent()
        server = self._create_gateway_server(name="Granted", url="https://granted.example.com/mcp")
        delegated = self._create_installation(scope="personal", gateway_server=server, url=server.url)
        MCPServiceAccountServerAccess.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user=self.user,
            service_account=account,
            gateway_server=server,
            installation=delegated,
            granted_by=self.user,
        )

        results = get_installations_for_sandbox(
            self.team.id,
            task_origin="support_reply",
            task_agent_key="support",
            credential_owner_id=self.user.id,
        )
        assert [result.id for result in results] == [str(delegated.id)]

        server.is_team_enabled = False
        server.save(update_fields=["is_team_enabled"])

        assert (
            get_installations_for_sandbox(
                self.team.id,
                task_origin="support_reply",
                task_agent_key="support",
                credential_owner_id=self.user.id,
            )
            == []
        )

    def test_other_users_personal_not_returned(self) -> None:
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        self._create_installation(scope="personal", user=other_user)

        results = get_installations_for_sandbox(self.team.id, user_id=self.user.id, include_personal=True)

        assert len(results) == 0

    def test_personal_wins_over_shared_for_same_url(self) -> None:
        # The user acts as themselves rather than through the shared credential.
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        url = "https://mcp.same.example.com/mcp"
        self._create_installation(scope="shared", user=other_user, url=url, display_name="Shared")
        personal = self._create_installation(scope="personal", url=url, display_name="Personal")

        results = get_installations_for_sandbox(self.team.id, user_id=self.user.id, include_personal=True)

        assert [r.id for r in results] == [str(personal.id)]
        assert results[0].scope == "personal"

    def test_shared_returned_for_same_url_without_include_personal(self) -> None:
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        url = "https://mcp.same.example.com/mcp"
        shared = self._create_installation(scope="shared", user=other_user, url=url)
        self._create_installation(scope="personal", url=url)

        results = get_installations_for_sandbox(self.team.id, user_id=self.user.id, include_personal=False)

        assert [r.id for r in results] == [str(shared.id)]
        assert results[0].scope == "shared"

    def test_different_urls_not_deduped(self) -> None:
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        self._create_installation(scope="shared", user=other_user, url="https://shared.example.com/mcp")
        self._create_installation(scope="personal", url="https://personal.example.com/mcp")

        results = get_installations_for_sandbox(self.team.id, user_id=self.user.id, include_personal=True)

        assert {r.scope for r in results} == {"shared", "personal"}

    @parameterized.expand(
        [
            ("shared_include_personal", "shared", True, True),
            ("shared_no_personal", "shared", False, True),
            ("personal_include_personal", "personal", True, True),
            ("personal_no_personal", "personal", False, False),
        ]
    )
    def test_scope_gating_matrix(self, _name: str, scope: str, include_personal: bool, expected_included: bool) -> None:
        self._create_installation(scope=scope)

        results = get_installations_for_sandbox(self.team.id, user_id=self.user.id, include_personal=include_personal)

        assert (len(results) == 1) == expected_included
