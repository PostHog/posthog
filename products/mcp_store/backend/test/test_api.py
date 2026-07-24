import hashlib
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from unittest.mock import patch

from django.core.signing import SignatureExpired
from django.http import HttpResponse
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import serializers, status
from rest_framework.test import APIClient

from posthog.models import Team
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import OrganizationMembership

from products.mcp_store.backend.agents import (
    create_gateway_agent_token,
    resolve_gateway_agent_token,
    sync_built_in_agents,
)
from products.mcp_store.backend.models import (
    MCPGatewayServer,
    MCPMemberServerRevocation,
    MCPOAuthState,
    MCPServerInstallation,
    MCPServerInstallationTool,
    MCPServerTemplate,
    MCPServiceAccount,
    MCPServiceAccountServerAccess,
    MCPToolPolicy,
    TeamMCPGatewayConfig,
)
from products.mcp_store.backend.presentation.gateway_views import (
    MAX_TOOL_POLICIES_PER_REQUEST,
    GatewayPoliciesUpsertSerializer,
    ServiceAccountAccessUpdateSerializer,
)
from products.mcp_store.backend.presentation.views import _is_valid_posthog_code_callback_url

ALLOW_URL = patch("products.mcp_store.backend.presentation.views.is_url_allowed", return_value=(True, None))

POLICY_REQUEST_SERIALIZER_CASES = [
    ("policy_upsert", GatewayPoliciesUpsertSerializer, {}),
    (
        "service_account_access",
        ServiceAccountAccessUpdateSerializer,
        {
            "gateway_server_id": "00000000-0000-0000-0000-000000000001",
            "enabled": True,
        },
    ),
]


class TestIsValidPosthogCodeCallbackUrl(TestCase):
    @parameterized.expand(
        [
            ("array_scheme", "array://callback", True),
            ("twig_scheme", "twig://oauth/callback", False),
            ("posthog_code_scheme", "posthog-code://oauth/callback", True),
            ("https_rejected", "https://evil.com/redirect", False),
            ("http_rejected", "http://example.com/callback", False),
            ("javascript_rejected", "javascript:alert(1)", False),
            ("empty_string", "", False),
        ]
    )
    def test_callback_url_validation(self, _name, url, expected):
        assert _is_valid_posthog_code_callback_url(url) == expected


class TestMCPServerTemplateIconKeyNormalization(TestCase):
    @parameterized.expand(
        [
            ("simple_lowercase", "notion", "notion"),
            ("titlecase", "Notion", "notion"),
            ("multi_word", "PostHog MCP", "posthog_mcp"),
            ("multi_space", "Cisco   ThousandEyes", "cisco_thousandeyes"),
            ("leading_trailing_whitespace", "  Linear  ", "linear"),
            ("empty", "", ""),
            ("whitespace_only", "   ", ""),
        ]
    )
    def test_save_normalizes_icon_key(self, _name, raw, expected):
        template = MCPServerTemplate.objects.create(
            name=f"Test-{_name}",
            url=f"https://mcp.example.com/{_name}",
            auth_type="api_key",
            icon_key=raw,
        )
        template.refresh_from_db()
        assert template.icon_key == expected

    @parameterized.expand(
        [
            ("bare_hostname", "linear.app", "linear.app"),
            ("uppercase_with_scheme", "HTTPS://Linear.APP/", "linear.app"),
            ("whitespace", "  notion.com ", "notion.com"),
            ("empty", "", ""),
            ("scheme_with_path", "https://linear.app/brand/assets", "linear.app"),
            ("bare_with_path", "linear.app/brand", "linear.app"),
            ("query_string", "linear.app?token=x", "linear.app"),
            ("port_and_trailing_dot", "linear.app.:8443", "linear.app"),
        ]
    )
    def test_save_normalizes_icon_domain(self, _name, raw, expected):
        # Admin- or sync-set values must land as bare lowercase hostnames, or the
        # logo.dev proxy URL the frontend builds from them 404s.
        template = MCPServerTemplate.objects.create(
            name=f"Test-domain-{_name}",
            url=f"https://mcp.example.com/domain-{_name}",
            auth_type="api_key",
            icon_domain=raw,
        )
        template.refresh_from_db()
        assert template.icon_domain == expected


class TestMCPGatewayRequestSerializerValidation(SimpleTestCase):
    @parameterized.expand(POLICY_REQUEST_SERIALIZER_CASES)
    def test_rejects_tool_names_longer_than_database_field(
        self,
        _name: str,
        serializer_class: type[serializers.Serializer],
        base_data: dict[str, object],
    ) -> None:
        serializer = serializer_class(
            data={
                **base_data,
                "policies": [{"tool_name": "x" * 201, "policy_state": "approved"}],
            }
        )

        assert not serializer.is_valid()
        assert serializer.errors["policies"][0]["tool_name"][0].code == "max_length"

    @parameterized.expand(POLICY_REQUEST_SERIALIZER_CASES)
    def test_rejects_oversized_policy_batches(
        self,
        _name: str,
        serializer_class: type[serializers.Serializer],
        base_data: dict[str, object],
    ) -> None:
        serializer = serializer_class(
            data={
                **base_data,
                "policies": [
                    {"tool_name": f"tool_{index}", "policy_state": "approved"}
                    for index in range(MAX_TOOL_POLICIES_PER_REQUEST + 1)
                ],
            }
        )

        assert not serializer.is_valid()
        assert serializer.errors["policies"][0].code == "max_length"


class TestMCPServerAPI(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def _create_active_template(self, **overrides) -> MCPServerTemplate:
        import uuid as _uuid

        defaults = {
            "name": f"Test-{_uuid.uuid4().hex[:6]}",
            "url": f"https://mcp.test-{_uuid.uuid4().hex[:8]}.example.com/mcp",
            "description": "Test integration",
            "auth_type": "oauth",
            "icon_key": "test",
            "is_active": True,
            "oauth_metadata": {
                "authorization_endpoint": "https://auth.test.example.com/authorize",
                "token_endpoint": "https://auth.test.example.com/token",
            },
            "oauth_credentials": {"client_id": "test-client-id"},
        }
        defaults.update(overrides)
        return MCPServerTemplate.objects.create(**defaults)

    def test_list_servers_returns_active_templates(self):
        active_a = self._create_active_template()
        active_b = self._create_active_template()
        self._create_active_template(is_active=False)

        response = self.client.get(f"/api/environments/{self.team.id}/mcp_servers/")
        assert response.status_code == status.HTTP_200_OK
        names = {s["name"] for s in response.json()["results"]}
        assert {active_a.name, active_b.name}.issubset(names)
        # Inactive templates must not be in the listing (check by name not presence of hidden)
        inactive_names = set(MCPServerTemplate.objects.filter(is_active=False).values_list("name", flat=True))
        assert inactive_names.isdisjoint(names)

    def test_list_servers_entries_match_serializer_schema(self):
        self._create_active_template()
        response = self.client.get(f"/api/environments/{self.team.id}/mcp_servers/")
        expected_keys = {
            "id",
            "name",
            "url",
            "docs_url",
            "description",
            "auth_type",
            "icon_key",
            "icon_domain",
            "category",
        }
        results = response.json()["results"]
        assert len(results) >= 1
        for entry in results:
            assert set(entry.keys()) == expected_keys

    def test_create_not_allowed(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_servers/",
            data={"name": "My Server", "url": "https://mcp.example.com"},
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    @parameterized.expand(
        [
            ("path_traversal", "linear.app/../evil"),
            ("full_url", "https://evil.example"),
            ("query_injection", "linear.app?token=steal"),
            ("empty", ""),
            ("single_label", "localhost"),
            ("overlong_hostname", "a." * 127 + "com"),
        ]
    )
    def test_icon_rejects_non_hostname_domains(self, _name, bad_domain):
        # The domain param becomes a path segment of img.logo.dev/{domain} — anything but a bare
        # hostname must be rejected or the endpoint can be steered off the logo host.
        response = self.client.get(f"/api/environments/{self.team.id}/mcp_servers/icon/", data={"domain": bad_domain})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand(
        [
            ("no_theme", {"domain": "linear.app"}, None),
            ("dark_theme", {"domain": "linear.app", "theme": "dark"}, "dark"),
            ("unknown_theme_dropped", {"domain": "linear.app", "theme": "neon"}, None),
            ("case_and_fqdn_dot_canonicalized", {"domain": "LINEAR.APP."}, None),
        ]
    )
    def test_icon_proxies_valid_domain(self, _name, params, expected_theme):
        # Both halves of the icon cache key must stay canonical: unknown themes are dropped
        # rather than forwarded, and the domain is lowercased with any FQDN trailing dot
        # stripped so case variants can't mint separate cache entries.
        with patch("products.mcp_store.backend.presentation.views.CDPIconsService") as service:
            service.return_value.get_icon_http_response.return_value = HttpResponse(b"png", content_type="image/png")
            response = self.client.get(f"/api/environments/{self.team.id}/mcp_servers/icon/", data=params)
        assert response.status_code == status.HTTP_200_OK
        service.return_value.get_icon_http_response.assert_called_once_with(
            "linear.app", theme=expected_theme, fallback="404", team_id=self.team.id
        )

    def test_icon_allows_oauth_project_read_scope(self):
        oauth_application = OAuthApplication.objects.create(
            name="MCP icon test",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=oauth_application,
            token="pha_test_mcp_icon",
            expires=timezone.now() + timedelta(hours=1),
            scope="project:read",
        )
        client = APIClient()

        with patch("products.mcp_store.backend.presentation.views.CDPIconsService") as service:
            service.return_value.get_icon_http_response.return_value = HttpResponse(b"png", content_type="image/png")
            response = client.get(
                f"/api/environments/{self.team.id}/mcp_servers/icon/",
                data={"domain": "linear.app"},
                headers={"authorization": f"Bearer {access_token.token}"},
            )

        assert response.status_code == status.HTTP_200_OK

    def test_unauthenticated_access(self):
        client = APIClient()
        response = client.get(f"/api/environments/{self.team.id}/mcp_servers/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestMCPGatewayServerAPI(APIBaseTest):
    def _api_url(self, suffix: str = "") -> str:
        base = f"/api/projects/{self.team.id}/mcp_gateway/servers/"
        return f"{base}{suffix}" if suffix else base

    def _make_admin(self) -> None:
        membership = self.user.organization_memberships.get(organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

    def _make_member(self) -> None:
        membership = self.user.organization_memberships.get(organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

    def _template(self, name: str, *, active: bool = True) -> MCPServerTemplate:
        return MCPServerTemplate.objects.create(
            name=name,
            url=f"https://mcp.{name.lower()}.gateway-test.example.com/mcp",
            description=f"{name} integration",
            auth_type="oauth",
            category="dev",
            is_active=active,
        )

    def _server_with_personal_tool(
        self, *, approval_state: str = "approved"
    ) -> tuple[MCPGatewayServer, MCPServerInstallation, MCPServerInstallationTool]:
        server = MCPGatewayServer.objects.for_team(self.team.id).create(
            team=self.team,
            name="Ceiling test",
            url="https://mcp.ceiling-test.example.com/mcp",
            created_by=self.user,
        )
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name=server.name,
            url=server.url,
            auth_type="api_key",
            sensitive_configuration={"api_key": "secret"},
            scope="personal",
            gateway_server=server,
        )
        tool = MCPServerInstallationTool.objects.create(
            installation=installation,
            tool_name="create_issue",
            description="Create an issue",
            approval_state=approval_state,
            last_seen_at=timezone.now(),
        )
        return server, installation, tool

    def test_admin_list_registers_active_catalog_templates_enabled_by_default(self) -> None:
        self._make_admin()
        created = self._template("Created")
        linked = self._template("Linked")
        inactive = self._template("Inactive", active=False)
        existing = MCPGatewayServer.objects.for_team(self.team.id).create(
            team=self.team,
            name="Existing custom name",
            url=linked.url,
            description="Existing custom description",
            category="dev",
            created_by=self.user,
        )

        response = self.client.get(self._api_url())

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        by_template_id = {result["template_id"]: result for result in results if result["template_id"]}
        assert by_template_id[str(created.id)]["is_team_enabled"] is True
        assert by_template_id[str(linked.id)]["id"] == str(existing.id)
        assert str(inactive.id) not in by_template_id
        assert MCPGatewayServer.objects.for_team(self.team.id).filter(url=linked.url).count() == 1

    def test_disabled_catalog_server_is_hidden_from_members_but_visible_to_admins(self) -> None:
        self._make_admin()
        template = self._template("Visibility")
        list_response = self.client.get(self._api_url())
        server = next(result for result in list_response.json()["results"] if result["template_id"] == str(template.id))

        self._make_member()
        default_member_response = self.client.get(self._api_url())
        assert server["id"] in {result["id"] for result in default_member_response.json()["results"]}

        self._make_admin()
        update_response = self.client.patch(
            self._api_url(f"{server['id']}/"),
            data={"is_team_enabled": False},
            format="json",
        )
        assert update_response.status_code == status.HTTP_200_OK

        self._make_member()
        member_response = self.client.get(self._api_url())
        assert member_response.status_code == status.HTTP_200_OK
        assert server["id"] not in {result["id"] for result in member_response.json()["results"]}

        self._make_admin()
        admin_response = self.client.get(self._api_url())
        admin_result = next(result for result in admin_response.json()["results"] if result["id"] == server["id"])
        assert admin_result["is_team_enabled"] is False

    @parameterized.expand([("list", False), ("retrieve", True)])
    def test_member_metadata_is_visible_only_to_admins(self, _name: str, retrieve: bool) -> None:
        self._make_admin()
        server, own_installation, _tool = self._server_with_personal_tool()
        other_user = self._create_user("other-gateway-member@posthog.com")
        other_installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=other_user,
            display_name=server.name,
            url=server.url,
            auth_type="api_key",
            sensitive_configuration={"api_key": "other-secret"},
            scope="personal",
            gateway_server=server,
        )
        MCPMemberServerRevocation.objects.for_team(self.team.id).create(
            team=self.team,
            gateway_server=server,
            user=other_user,
            revoked_by=self.user,
        )
        url = self._api_url(f"{server.id}/") if retrieve else self._api_url()

        admin_response = self.client.get(url)

        assert admin_response.status_code == status.HTTP_200_OK
        admin_payload = (
            admin_response.json()
            if retrieve
            else next(result for result in admin_response.json()["results"] if result["id"] == str(server.id))
        )
        assert {connection["installation_id"] for connection in admin_payload["connections"]} == {
            str(own_installation.id),
            str(other_installation.id),
        }
        assert admin_payload["revoked_user_ids"] == [other_user.id]

        self._make_member()
        member_response = self.client.get(url)

        assert member_response.status_code == status.HTTP_200_OK
        member_payload = (
            member_response.json()
            if retrieve
            else next(result for result in member_response.json()["results"] if result["id"] == str(server.id))
        )
        assert member_payload["connections"] == []
        assert member_payload["revoked_user_ids"] == []
        assert member_payload["your_connection"]["installation_id"] == str(own_installation.id)
        assert member_payload["is_revoked_for_you"] is False

    def test_team_policy_is_a_ceiling_for_member_and_legacy_tool_views(self) -> None:
        self._make_admin()
        server, installation, _tool = self._server_with_personal_tool(approval_state="approved")
        MCPToolPolicy.objects.for_team(self.team.id).create(
            team=self.team,
            gateway_server=server,
            tool_name="create_issue",
            scope_type="member",
            scope_user=self.user,
            state="approved",
        )

        team_response = self.client.post(
            self._api_url(f"{server.id}/policies/"),
            data={
                "scope_type": "team",
                "policies": [{"tool_name": "create_issue", "policy_state": "needs_approval"}],
            },
            format="json",
        )

        assert team_response.status_code == status.HTTP_200_OK
        assert team_response.json()["results"][0]["policy_state"] == "needs_approval"

        self._make_member()
        member_response = self.client.get(
            self._api_url(f"{server.id}/tools/"),
            {"scope_type": "member"},
        )
        assert member_response.status_code == status.HTTP_200_OK
        member_tool = member_response.json()["results"][0]
        assert member_tool["policy_state"] == "needs_approval"
        assert member_tool["team_state"] == "needs_approval"
        assert member_tool["decided_by"] == "team"
        assert member_tool["locked"] is False

        legacy_response = self.client.get(
            f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/tools/"
        )
        assert legacy_response.status_code == status.HTTP_200_OK
        legacy_tool = legacy_response.json()["results"][0]
        assert legacy_tool["approval_state"] == "needs_approval"
        assert legacy_tool["team_state"] == "needs_approval"
        assert legacy_tool["decided_by"] == "team"
        assert legacy_tool["locked"] is False

    def test_policy_upsert_rejects_oversized_tool_names_without_writes(self) -> None:
        self._make_admin()
        server, _installation, _tool = self._server_with_personal_tool()

        response = self.client.post(
            self._api_url(f"{server.id}/policies/"),
            data={
                "scope_type": "team",
                "policies": [{"tool_name": "x" * 201, "policy_state": "approved"}],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not MCPToolPolicy.objects.for_team(self.team.id).filter(gateway_server=server).exists()

    def test_member_can_choose_below_team_ceiling_but_not_above_it(self) -> None:
        self._make_admin()
        server, installation, _tool = self._server_with_personal_tool(approval_state="needs_approval")
        team_response = self.client.post(
            self._api_url(f"{server.id}/policies/"),
            data={
                "scope_type": "team",
                "policies": [{"tool_name": "create_issue", "policy_state": "needs_approval"}],
            },
            format="json",
        )
        assert team_response.status_code == status.HTTP_200_OK

        self._make_member()
        stricter_response = self.client.post(
            self._api_url(f"{server.id}/policies/"),
            data={
                "scope_type": "member",
                "policies": [{"tool_name": "create_issue", "policy_state": "do_not_use"}],
            },
            format="json",
        )
        assert stricter_response.status_code == status.HTTP_200_OK
        assert stricter_response.json()["results"][0]["policy_state"] == "do_not_use"
        assert stricter_response.json()["results"][0]["decided_by"] == "scope"

        above_ceiling_response = self.client.post(
            self._api_url(f"{server.id}/policies/"),
            data={
                "scope_type": "member",
                "policies": [{"tool_name": "create_issue", "policy_state": "approved"}],
            },
            format="json",
        )
        assert above_ceiling_response.status_code == status.HTTP_400_BAD_REQUEST

        legacy_above_ceiling_response = self.client.patch(
            f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/tools/create_issue/",
            data={"approval_state": "approved"},
            format="json",
        )
        assert legacy_above_ceiling_response.status_code == status.HTTP_400_BAD_REQUEST

    def test_member_policy_ceiling_uses_latest_known_description_across_installations(self) -> None:
        self._make_admin()
        server, _installation, latest_tool = self._server_with_personal_tool()
        now = timezone.now()
        latest_tool.tool_name = "manage_issue"
        latest_tool.description = "Permanently delete the issue"
        latest_tool.last_seen_at = now
        latest_tool.save(update_fields=["tool_name", "description", "last_seen_at", "updated_at"])
        older_installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name=server.name,
            url=server.url,
            auth_type="api_key",
            sensitive_configuration={"api_key": "shared-secret"},
            scope="shared",
            gateway_server=server,
        )
        MCPServerInstallationTool.objects.create(
            installation=older_installation,
            tool_name=latest_tool.tool_name,
            description="Inspect issue details",
            approval_state="approved",
            last_seen_at=now - timedelta(hours=1),
        )
        TeamMCPGatewayConfig.objects.for_team(self.team.id).create(
            team=self.team,
            member_default_preset="block",
        )
        request_data = {
            "scope_type": "member",
            "policies": [{"tool_name": latest_tool.tool_name, "policy_state": "approved"}],
        }

        tools_response = self.client.get(
            self._api_url(f"{server.id}/tools/"),
            {"scope_type": "member"},
        )
        active_response = self.client.post(
            self._api_url(f"{server.id}/policies/"),
            data=request_data,
            format="json",
        )

        assert tools_response.status_code == status.HTTP_200_OK
        assert tools_response.json()["results"][0]["team_state"] == "do_not_use"
        assert active_response.status_code == status.HTTP_400_BAD_REQUEST

        MCPServerInstallationTool.objects.filter(
            installation__gateway_server=server,
            tool_name=latest_tool.tool_name,
        ).update(removed_at=now)

        removed_response = self.client.post(
            self._api_url(f"{server.id}/policies/"),
            data=request_data,
            format="json",
        )

        assert removed_response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            not MCPToolPolicy.objects.for_team(self.team.id)
            .filter(
                gateway_server=server,
                scope_type="member",
                scope_user=self.user,
                tool_name=latest_tool.tool_name,
            )
            .exists()
        )

    def test_legacy_tool_approval_updates_reuse_policy_for_child_environment(self) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child environment")
        server = MCPGatewayServer.objects.for_team(child.id).create(
            team=child,
            name="Child environment server",
            url="https://mcp.child-environment.example.com/mcp",
            created_by=self.user,
        )
        installation = MCPServerInstallation.objects.create(
            team=child,
            user=self.user,
            display_name=server.name,
            url=server.url,
            auth_type="api_key",
            sensitive_configuration={"api_key": "secret"},
            scope="personal",
            gateway_server=server,
        )
        tool = MCPServerInstallationTool.objects.create(
            installation=installation,
            tool_name="child_tool",
            approval_state="approved",
            last_seen_at=timezone.now(),
        )
        url = f"/api/environments/{child.id}/mcp_server_installations/{installation.id}/tools/{tool.tool_name}/"

        first_response = self.client.patch(url, data={"approval_state": "do_not_use"}, format="json")
        second_response = self.client.patch(url, data={"approval_state": "needs_approval"}, format="json")

        assert first_response.status_code == status.HTTP_200_OK
        assert second_response.status_code == status.HTTP_200_OK
        policy = MCPToolPolicy.objects.for_team(self.team.id).get(
            gateway_server=server,
            scope_type="member",
            scope_user=self.user,
            tool_name=tool.tool_name,
        )
        assert policy.team_id == self.team.id
        assert policy.state == "needs_approval"

    def test_team_scope_displays_an_always_allow_ceiling(self) -> None:
        self._make_admin()
        server, _installation, _tool = self._server_with_personal_tool(approval_state="needs_approval")

        default_response = self.client.get(
            self._api_url(f"{server.id}/tools/"),
            {"scope_type": "team"},
        )

        assert default_response.status_code == status.HTTP_200_OK
        default_policy = default_response.json()["results"][0]
        assert default_policy["policy_state"] == "approved"
        assert default_policy["team_state"] is None
        assert default_policy["decided_by"] == "default"

        response = self.client.post(
            self._api_url(f"{server.id}/policies/"),
            data={
                "scope_type": "team",
                "policies": [{"tool_name": "create_issue", "policy_state": "approved"}],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        policy = response.json()["results"][0]
        assert policy["policy_state"] == "approved"
        assert policy["team_state"] == "approved"
        assert policy["decided_by"] == "team"

    def test_agent_access_policy_cannot_exceed_team_ceiling(self) -> None:
        self._make_admin()
        server, _installation, _tool = self._server_with_personal_tool(approval_state="needs_approval")
        account = sync_built_in_agents(self.team)[0]
        team_response = self.client.post(
            self._api_url(f"{server.id}/policies/"),
            data={
                "scope_type": "team",
                "policies": [{"tool_name": "create_issue", "policy_state": "needs_approval"}],
            },
            format="json",
        )
        assert team_response.status_code == status.HTTP_200_OK

        response = self.client.post(
            f"/api/projects/{self.team.id}/mcp_gateway/service_accounts/{account.id}/access/",
            data={
                "gateway_server_id": str(server.id),
                "enabled": True,
                "policies": [{"tool_name": "create_issue", "policy_state": "approved"}],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            not MCPToolPolicy.objects.for_team(self.team.id)
            .filter(
                gateway_server=server,
                scope_type="agent",
                scope_service_account=account,
            )
            .exists()
        )


class TestMCPServiceAccountAPI(APIBaseTest):
    def _api_url(self, suffix: str = "") -> str:
        base = f"/api/projects/{self.team.id}/mcp_gateway/service_accounts/"
        return f"{base}{suffix}" if suffix else base

    def _make_admin(self) -> None:
        membership = self.user.organization_memberships.get(organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

    def _make_member(self) -> None:
        membership = self.user.organization_memberships.get(organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

    def _active_posthog_ai_account(self) -> MCPServiceAccount:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        return next(agent for agent in sync_built_in_agents(self.team) if agent.handle == "posthog-ai")

    @staticmethod
    def _agent_client(account: MCPServiceAccount, token: str | None = None) -> APIClient:
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token or create_gateway_agent_token(account)}")
        return client

    def _oauth_client(self, *, built_in_agent: bool) -> APIClient:
        application = OAuthApplication.objects.create(
            name="Sandbox agent",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        scopes = ["project:read", "project:write"]
        if built_in_agent:
            scopes.append("mcp_builtin_agent:read")
        access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token=f"pha_mcp_agent_{'built_in' if built_in_agent else 'generic'}",
            expires=timezone.now() + timedelta(hours=1),
            scope=" ".join(scopes),
            scoped_teams=[self.team.id],
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token.token}")
        return client

    def test_list_materializes_only_the_fixed_posthog_agent_catalog(self) -> None:
        self._make_admin()
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

        response = self.client.get(self._api_url())

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert [agent["agent_key"] for agent in results] == ["support", "scout", "posthog_ai"]
        assert [agent["handle"] for agent in results] == ["posthog-support", "posthog-scout", "posthog-ai"]
        assert all(agent["product_enabled"] is False for agent in results)
        assert all(agent["status"] == "paused" for agent in results)
        assert MCPServiceAccount.objects.for_team(self.team.id).count() == 3

    def test_list_reconciles_legacy_built_in_agent_handles(self) -> None:
        self._make_admin()
        support_account = sync_built_in_agents(self.team)[0]
        MCPServiceAccount.objects.for_team(self.team.id).filter(id=support_account.id).update(
            handle="svc-posthog-support"
        )

        response = self.client.get(self._api_url())

        assert response.status_code == status.HTTP_200_OK
        support_account.refresh_from_db()
        assert support_account.handle == "posthog-support"
        assert response.json()["results"][0]["id"] == str(support_account.id)
        assert MCPServiceAccount.objects.for_team(self.team.id).count() == 3

    def test_agents_cannot_be_created_or_deleted(self) -> None:
        self._make_admin()

        create_response = self.client.post(self._api_url(), data={"name": "Custom agent"}, format="json")
        account_id = self.client.get(self._api_url()).json()["results"][0]["id"]
        delete_response = self.client.delete(self._api_url(f"{account_id}/"))

        assert create_response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert delete_response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    @ALLOW_URL
    def test_member_can_delegate_a_personal_credential_during_install(self, _mock_is_url_allowed) -> None:
        self._make_member()
        account = sync_built_in_agents(self.team)[0]
        install_url = "https://mcp.personal-agent-grant.example.com/mcp"

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={
                "name": "Personal grant",
                "url": install_url,
                "auth_type": "api_key",
                "api_key": "secret",
                "scope": "personal",
                "agent_ids": [str(account.id)],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        installation = MCPServerInstallation.objects.get(team=self.team, url=install_url)
        access = MCPServiceAccountServerAccess.objects.for_team(self.team.id).get(
            service_account=account,
            gateway_server=installation.gateway_server,
        )
        assert installation.scope == "personal"
        assert access.installation == installation

    @ALLOW_URL
    def test_install_rejects_member_agent_grant_when_team_setting_is_off(self, _mock_is_url_allowed) -> None:
        self._make_member()
        TeamMCPGatewayConfig.objects.for_team(self.team.id).create(team=self.team, allow_member_agent_access=False)
        account = sync_built_in_agents(self.team)[0]
        install_url = "https://mcp.restricted-agent-grant.example.com/mcp"

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={
                "name": "Restricted grant",
                "url": install_url,
                "auth_type": "api_key",
                "api_key": "secret",
                "scope": "personal",
                "agent_ids": [str(account.id)],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not MCPServerInstallation.objects.filter(team=self.team, url=install_url).exists()

    @ALLOW_URL
    def test_install_rejects_hidden_legacy_service_account(self, _mock_is_url_allowed) -> None:
        self._make_admin()
        legacy_account = MCPServiceAccount.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            name="Legacy custom agent",
            handle="svc-legacy-custom-agent",
            token_hash="legacy-custom-agent-token-hash",
        )
        install_url = "https://mcp.legacy-agent-grant.example.com/mcp"

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={
                "name": "Legacy grant",
                "url": install_url,
                "auth_type": "api_key",
                "api_key": "secret",
                "scope": "shared",
                "agent_ids": [str(legacy_account.id)],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not MCPServerInstallation.objects.filter(team=self.team, url=install_url).exists()

    def test_member_can_delegate_their_credential_and_control_agent_tools_by_default(self) -> None:
        self._make_member()
        account = sync_built_in_agents(self.team)[1]
        server = MCPGatewayServer.objects.for_team(self.team.id).create(
            team=self.team,
            name="Personal Notion",
            url="https://mcp.personal-notion.example.com/mcp",
        )
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="Personal Notion",
            url=server.url,
            auth_type="api_key",
            sensitive_configuration={"api_key": "secret"},
            scope="personal",
            gateway_server=server,
        )
        MCPServerInstallationTool.objects.create(
            installation=installation,
            tool_name="create_issue",
            description="Create an issue",
            last_seen_at=timezone.now(),
        )

        response = self.client.post(
            self._api_url(f"{account.id}/access/"),
            data={
                "gateway_server_id": str(server.id),
                "enabled": True,
                "policies": [{"tool_name": "create_issue", "policy_state": "do_not_use"}],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        access = MCPServiceAccountServerAccess.objects.for_team(self.team.id).get(
            service_account=account,
            gateway_server=server,
        )
        assert access.installation == installation
        assert access.installation.scope == "personal"
        assert server.auth_mode == "individual"
        assert (
            MCPToolPolicy.objects.for_team(self.team.id)
            .get(
                gateway_server=server,
                scope_type="agent",
                scope_service_account=account,
                tool_name="create_issue",
            )
            .state
            == "do_not_use"
        )

        policy_response = self.client.post(
            f"/api/projects/{self.team.id}/mcp_gateway/servers/{server.id}/policies/",
            data={
                "scope_type": "agent",
                "scope_service_account_id": str(account.id),
                "policies": [{"tool_name": "create_issue", "policy_state": "needs_approval"}],
            },
            format="json",
        )
        assert policy_response.status_code == status.HTTP_200_OK
        assert policy_response.json()["results"][0]["policy_state"] == "needs_approval"

        member_response = self.client.get(self._api_url())
        scout = next(row for row in member_response.json()["results"] if row["agent_key"] == "scout")
        assert scout["servers"] == [
            {
                "id": str(server.id),
                "name": "Personal Notion",
                "description": "",
                "icon_key": "",
                "icon_domain": "",
                "connection_state": "ready",
            }
        ]

    def test_restricted_member_cannot_change_existing_agent_access_but_admin_can(self) -> None:
        self._make_member()
        account = sync_built_in_agents(self.team)[0]
        server = MCPGatewayServer.objects.for_team(self.team.id).create(
            team=self.team,
            name="Restricted access",
            url="https://mcp.restricted-access.example.com/mcp",
        )
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name=server.name,
            url=server.url,
            auth_type="api_key",
            sensitive_configuration={"api_key": "secret"},
            scope="personal",
            gateway_server=server,
        )
        MCPServerInstallationTool.objects.create(
            installation=installation,
            tool_name="create_issue",
            last_seen_at=timezone.now(),
        )
        access = MCPServiceAccountServerAccess.objects.for_team(self.team.id).create(
            team=self.team,
            service_account=account,
            gateway_server=server,
            installation=installation,
            granted_by=self.user,
        )
        TeamMCPGatewayConfig.objects.for_team(self.team.id).create(team=self.team, allow_member_agent_access=False)

        policy_response = self.client.post(
            f"/api/projects/{self.team.id}/mcp_gateway/servers/{server.id}/policies/",
            data={
                "scope_type": "agent",
                "scope_service_account_id": str(account.id),
                "policies": [{"tool_name": "create_issue", "policy_state": "do_not_use"}],
            },
            format="json",
        )
        revoke_response = self.client.post(
            self._api_url(f"{account.id}/access/"),
            data={"gateway_server_id": str(server.id), "enabled": False},
            format="json",
        )

        assert policy_response.status_code == status.HTTP_403_FORBIDDEN
        assert revoke_response.status_code == status.HTTP_403_FORBIDDEN
        assert MCPServiceAccountServerAccess.objects.for_team(self.team.id).filter(id=access.id).exists()

        self._make_admin()
        admin_revoke_response = self.client.post(
            self._api_url(f"{account.id}/access/"),
            data={"gateway_server_id": str(server.id), "enabled": False},
            format="json",
        )
        assert admin_revoke_response.status_code == status.HTTP_200_OK
        assert not MCPServiceAccountServerAccess.objects.for_team(self.team.id).filter(id=access.id).exists()

    def test_only_admin_can_update_member_agent_access_setting(self) -> None:
        self._make_member()
        config_url = f"/api/projects/{self.team.id}/mcp_gateway/config/"
        response = self.client.get(config_url)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["allow_member_agent_access"] is True

        member_response = self.client.post(
            f"{config_url}update_settings/",
            data={"allow_member_agent_access": False},
            format="json",
        )
        assert member_response.status_code == status.HTTP_403_FORBIDDEN

        self._make_admin()
        admin_response = self.client.post(
            f"{config_url}update_settings/",
            data={"allow_member_agent_access": False},
            format="json",
        )
        assert admin_response.status_code == status.HTTP_200_OK
        assert admin_response.json()["allow_member_agent_access"] is False

    def test_member_can_see_legacy_agent_grant_that_needs_a_credential(self) -> None:
        account = sync_built_in_agents(self.team)[1]
        template = MCPServerTemplate.objects.create(
            name="Notion",
            url="https://mcp.notion-agent-summary.example.com/mcp",
            description="Notion workspace",
            auth_type="oauth",
            icon_key="notion",
            icon_domain="notion.so",
            is_active=True,
        )
        server = MCPGatewayServer.objects.for_team(self.team.id).create(
            team=self.team,
            template=template,
            name=template.name,
            url=template.url,
            description=template.description,
        )
        MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            template=template,
            display_name=template.name,
            url=server.url,
            auth_type="oauth",
            scope="personal",
            gateway_server=server,
            sensitive_configuration={"access_token": "personal-token"},
        )
        MCPServiceAccountServerAccess.objects.for_team(self.team.id).create(
            team=self.team,
            service_account=account,
            gateway_server=server,
            granted_by=self.user,
        )
        self._make_member()

        response = self.client.get(self._api_url())

        assert response.status_code == status.HTTP_200_OK
        scout = next(row for row in response.json()["results"] if row["agent_key"] == "scout")
        assert scout["servers"] == [
            {
                "id": str(server.id),
                "name": "Notion",
                "description": "Notion workspace",
                "icon_key": "notion",
                "icon_domain": "notion.so",
                "connection_state": "missing_credential",
            }
        ]

    @patch("products.mcp_store.backend.agents.is_team_limited", return_value=False)
    def test_product_becoming_unavailable_pauses_agent_and_prevents_resume(self, _mock_is_limited) -> None:
        self._make_admin()
        account = self._active_posthog_ai_account()
        assert account.status == "active"

        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

        list_response = self.client.get(self._api_url())
        account_row = next(row for row in list_response.json()["results"] if row["id"] == str(account.id))
        resume_response = self.client.patch(
            self._api_url(f"{account.id}/"),
            data={"status": "active"},
            format="json",
        )

        account.refresh_from_db()
        assert list_response.status_code == status.HTTP_200_OK
        assert account_row["product_enabled"] is False
        assert account_row["status"] == "paused"
        assert account.status == "paused"
        assert resume_response.status_code == status.HTTP_403_FORBIDDEN

    @patch("products.mcp_store.backend.agents.is_team_limited")
    def test_agent_token_stops_resolving_when_billing_quota_is_reached(self, mock_is_limited) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        mock_is_limited.return_value = False
        account = next(agent for agent in sync_built_in_agents(self.team) if agent.handle == "posthog-ai")
        token = create_gateway_agent_token(account)
        assert resolve_gateway_agent_token(token) == account

        mock_is_limited.return_value = True

        assert resolve_gateway_agent_token(token) is None

    @patch("products.mcp_store.backend.agents.is_team_limited", return_value=False)
    def test_agent_endpoint_rejects_tampered_signed_token(self, _mock_is_limited) -> None:
        account = self._active_posthog_ai_account()
        token = create_gateway_agent_token(account)
        tampered_token = f"{token[:-1]}{'a' if token[-1] != 'a' else 'b'}"

        response = self._agent_client(account, tampered_token).get("/api/mcp_store/gateway/servers/")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch("products.mcp_store.backend.agents.is_team_limited", return_value=False)
    def test_agent_endpoint_rejects_expired_signed_token(self, _mock_is_limited) -> None:
        account = self._active_posthog_ai_account()
        client = self._agent_client(account)

        with patch(
            "products.mcp_store.backend.agents.signing.loads",
            side_effect=SignatureExpired("Gateway token expired"),
        ):
            response = client.get("/api/mcp_store/gateway/servers/")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch("products.mcp_store.backend.agents.is_team_limited", return_value=False)
    def test_agent_endpoint_rechecks_pause_and_product_availability_after_mint(self, _mock_is_limited) -> None:
        account = self._active_posthog_ai_account()
        token = create_gateway_agent_token(account)
        client = self._agent_client(account, token)

        account.status = "paused"
        account.save(update_fields=["status", "updated_at"])
        assert client.get("/api/mcp_store/gateway/servers/").status_code == status.HTTP_401_UNAUTHORIZED

        account.status = "active"
        account.save(update_fields=["status", "updated_at"])
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        assert client.get("/api/mcp_store/gateway/servers/").status_code == status.HTTP_401_UNAUTHORIZED

    @parameterized.expand(
        [
            ("ungranted",),
            ("revoked",),
            ("cross_team",),
        ]
    )
    @patch("products.mcp_store.backend.agents.is_team_limited", return_value=False)
    @patch("products.mcp_store.backend.presentation.agent_views.proxy_mcp_request")
    def test_agent_proxy_hides_servers_outside_its_grant_set(self, scenario: str, mock_proxy, _mock_is_limited) -> None:
        account = self._active_posthog_ai_account()
        server_team = self.team
        if scenario == "cross_team":
            server_team = self.organization.teams.create(name="Other gateway team")
        server = MCPGatewayServer.objects.for_team(server_team.id).create(
            team=server_team,
            name=f"Hidden {scenario}",
            url=f"https://mcp.{scenario}.example.com/mcp",
        )
        if scenario == "revoked":
            access = MCPServiceAccountServerAccess.objects.for_team(self.team.id).create(
                team=self.team,
                service_account=account,
                gateway_server=server,
                granted_by=self.user,
            )
            access.delete()

        response = self._agent_client(account).post(
            f"/api/mcp_store/gateway/servers/{server.id}/proxy/",
            data={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_proxy.assert_not_called()

    @patch("products.mcp_store.backend.agents.is_team_limited", return_value=False)
    @patch("products.mcp_store.backend.proxy.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_agent_grant_works_with_member_access_off_and_still_enforces_policy(
        self, mock_http_client, _mock_is_url_allowed, _mock_is_limited
    ) -> None:
        account = self._active_posthog_ai_account()
        server = MCPGatewayServer.objects.for_team(self.team.id).create(
            team=self.team,
            name="Agent policy",
            url="https://mcp.agent-policy.example.com/mcp",
            is_team_enabled=False,
        )
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="Shared agent credential",
            url=server.url,
            auth_type="api_key",
            sensitive_configuration={"api_key": "secret"},
            scope="shared",
            gateway_server=server,
        )
        MCPServerInstallationTool.objects.create(
            installation=installation,
            tool_name="delete_everything",
            last_seen_at=timezone.now(),
        )
        MCPServiceAccountServerAccess.objects.for_team(self.team.id).create(
            team=self.team,
            service_account=account,
            gateway_server=server,
            granted_by=self.user,
        )
        MCPToolPolicy.objects.for_team(self.team.id).create(
            team=self.team,
            gateway_server=server,
            tool_name="delete_everything",
            scope_type="agent",
            scope_service_account=account,
            state="do_not_use",
        )

        response = self._agent_client(account).post(
            f"/api/mcp_store/gateway/servers/{server.id}/proxy/",
            data={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 1,
                "params": {"name": "delete_everything", "arguments": {}},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["error"]["code"] == -32002
        mock_http_client.assert_not_called()

    def test_explicit_agent_grant_is_independent_of_team_member_access(self) -> None:
        self._make_admin()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        catalog_response = self.client.get(self._api_url())
        posthog_ai = next(agent for agent in catalog_response.json()["results"] if agent["agent_key"] == "posthog_ai")
        granted_server = MCPGatewayServer.objects.for_team(self.team.id).create(
            team=self.team,
            name="Agent only",
            url="https://mcp.agent-only.example.com/mcp",
            is_team_enabled=False,
        )
        shared_installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="Shared",
            url=granted_server.url,
            auth_type="api_key",
            scope="shared",
            gateway_server=granted_server,
        )
        personal_installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="Personal",
            url=granted_server.url,
            auth_type="api_key",
            scope="personal",
            gateway_server=granted_server,
        )
        MCPServerInstallationTool.objects.create(
            installation=shared_installation,
            tool_name="shared_tool",
            last_seen_at=timezone.now(),
        )
        MCPServerInstallationTool.objects.create(
            installation=personal_installation,
            tool_name="personal_tool",
            last_seen_at=timezone.now(),
        )
        MCPGatewayServer.objects.for_team(self.team.id).create(
            team=self.team,
            name="Not granted",
            url="https://mcp.not-granted.example.com/mcp",
        )

        grant_response = self.client.post(
            self._api_url(f"{posthog_ai['id']}/access/"),
            data={"gateway_server_id": str(granted_server.id), "enabled": True},
            format="json",
        )
        assert grant_response.status_code == status.HTTP_200_OK
        access = MCPServiceAccountServerAccess.objects.for_team(self.team.id).get(
            service_account_id=posthog_ai["id"],
            gateway_server=granted_server,
        )
        assert access.installation == personal_installation
        assert grant_response.json()["servers"] == [
            {
                "id": str(granted_server.id),
                "name": "Agent only",
                "description": "",
                "icon_key": "",
                "icon_domain": "",
                "connection_state": "ready",
            }
        ]

        account = MCPServiceAccount.objects.for_team(self.team.id).get(id=posthog_ai["id"])
        agent_client = APIClient()
        agent_client.credentials(HTTP_AUTHORIZATION=f"Bearer {create_gateway_agent_token(account)}")
        response = agent_client.get("/api/mcp_store/gateway/servers/")

        assert response.status_code == status.HTTP_200_OK
        assert [server["id"] for server in response.json()["results"]] == [str(granted_server.id)]
        assert [tool["name"] for tool in response.json()["results"][0]["tools"]] == ["personal_tool"]

        revoke_response = self.client.post(
            self._api_url(f"{posthog_ai['id']}/access/"),
            data={"gateway_server_id": str(granted_server.id), "enabled": False},
            format="json",
        )
        revoked_catalog_response = agent_client.get("/api/mcp_store/gateway/servers/")

        assert revoke_response.status_code == status.HTTP_200_OK
        assert str(granted_server.id) not in revoke_response.json()["server_ids"]
        assert revoked_catalog_response.status_code == status.HTTP_200_OK
        assert revoked_catalog_response.json()["results"] == []

    def test_built_in_agent_oauth_cannot_use_member_mcp_or_control_plane(self) -> None:
        self._make_admin()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        catalog = self.client.get(self._api_url()).json()["results"]
        account = next(agent for agent in catalog if agent["agent_key"] == "posthog_ai")
        server = MCPGatewayServer.objects.for_team(self.team.id).create(
            team=self.team,
            name="Restricted",
            url="https://mcp.restricted.example.com/mcp",
        )
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="Personal",
            url=server.url,
            auth_type="api_key",
            gateway_server=server,
        )
        client = self._oauth_client(built_in_agent=True)

        assert client.get(f"/api/environments/{self.team.id}/mcp_server_installations/").status_code == 403
        assert (
            client.get(f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/").status_code
            == 403
        )
        assert (
            client.post(
                f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/proxy/"
            ).status_code
            == 403
        )
        assert (
            client.patch(
                f"/api/projects/{self.team.id}/mcp_gateway/servers/{server.id}/",
                data={"is_team_enabled": False},
                format="json",
            ).status_code
            == 403
        )
        assert (
            client.post(
                self._api_url(f"{account['id']}/access/"),
                data={"gateway_server_id": str(server.id), "enabled": True},
                format="json",
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/share/"
            ).status_code
            == 403
        )

        server.refresh_from_db()
        installation.refresh_from_db()
        assert server.is_team_enabled is True
        assert installation.scope == "personal"
        assert not MCPServiceAccountServerAccess.objects.for_team(self.team.id).exists()

    def test_generic_sandbox_oauth_keeps_member_mcp_access(self) -> None:
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="Personal",
            url="https://mcp.generic-sandbox.example.com/mcp",
            auth_type="api_key",
        )
        client = self._oauth_client(built_in_agent=False)

        response = client.get(f"/api/environments/{self.team.id}/mcp_server_installations/")

        assert response.status_code == status.HTTP_200_OK
        assert [row["id"] for row in response.json()["results"]] == [str(installation.id)]


class TestMCPServerInstallationAPI(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def test_create_not_allowed(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/",
            data={"url": "https://mcp.example.com", "display_name": "Test"},
            format="json",
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_list_installations(self):
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="Test Server",
            url="https://mcp.example.com",
            auth_type="api_key",
        )

        response = self.client.get(f"/api/environments/{self.team.id}/mcp_server_installations/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["id"] == str(installation.id)
        assert results[0]["name"] == "Test Server"
        assert results[0]["icon_domain"] == ""
        assert results[0]["icon_key"] == ""

    def test_list_installation_icon_fields_from_template(self):
        # Pass non-normalized icon values to confirm the model's save() normalizes them and
        # both flow through the serializer — icon_key must stay exposed alongside icon_domain
        # until PostHog Code stops reading it.
        template = MCPServerTemplate.objects.create(
            name="PostHog MCP",
            url="https://mcp.notion.example/mcp",
            description="d",
            auth_type="api_key",
            is_active=True,
            icon_domain="HTTPS://Notion.example/",
            icon_key="PostHog MCP",
        )
        MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            template=template,
            display_name="",
            url=template.url,
            auth_type="api_key",
        )
        response = self.client.get(f"/api/environments/{self.team.id}/mcp_server_installations/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"][0]["icon_domain"] == "notion.example"
        assert response.json()["results"][0]["icon_key"] == "posthog_mcp"

    def test_uninstall_server(self):
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="Test Server",
            url="https://mcp.example.com",
            auth_type="api_key",
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not MCPServerInstallation.objects.filter(id=installation.id).exists()

    def test_update_installation(self):
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="Original",
            url="https://mcp.example.com",
            description="Old description",
            auth_type="api_key",
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/",
            data={"display_name": "Updated", "description": "New description"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["display_name"] == "Updated"
        assert response.json()["name"] == "Updated"
        assert response.json()["description"] == "New description"

    def test_put_not_allowed(self):
        # PUT is disabled: it would bypass the field allowlist and shared-row
        # ownership guard that partial_update (PATCH) enforces.
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="Original",
            url="https://mcp.example.com",
            auth_type="api_key",
        )

        response = self.client.put(
            f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/",
            data={"display_name": "Updated", "url": "https://evil.example.com", "auth_type": "oauth"},
            format="json",
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        installation.refresh_from_db()
        assert installation.url == "https://mcp.example.com"
        assert installation.auth_type == "api_key"

    def test_toggle_installation_enabled(self):
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="Toggle Test",
            url="https://mcp.example.com",
            auth_type="api_key",
            is_enabled=False,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/",
            data={"is_enabled": True},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["is_enabled"] is True
        installation.refresh_from_db()
        assert installation.is_enabled is True

    def test_list_installations_includes_is_enabled(self):
        MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="Enabled Server",
            url="https://mcp.enabled.com",
            auth_type="api_key",
            is_enabled=True,
        )
        MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="Disabled Server",
            url="https://mcp.disabled.com",
            auth_type="api_key",
            is_enabled=False,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/mcp_server_installations/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 2
        by_name = {r["name"]: r for r in results}
        assert by_name["Enabled Server"]["is_enabled"] is True
        assert by_name["Disabled Server"]["is_enabled"] is False

    def test_user_isolation(self):
        MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="Test Server",
            url="https://mcp.example.com",
            auth_type="api_key",
        )

        from posthog.models import User

        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        other_installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=other_user,
            display_name="Test Server",
            url="https://mcp2.example.com",
            auth_type="api_key",
        )

        response = self.client.get(f"/api/environments/{self.team.id}/mcp_server_installations/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["id"] != str(other_installation.id)


class TestInstallCustomAPI(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    @ALLOW_URL
    def test_install_custom_api_key_server(self, _mock):
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

    @ALLOW_URL
    def test_install_custom_api_key_server_without_key(self, _mock):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Open Server", "url": "https://mcp.open.com", "auth_type": "api_key"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["auth_type"] == "api_key"

    def test_install_custom_none_auth_type_rejected(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Server", "url": "https://mcp.example.com", "auth_type": "none"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @ALLOW_URL
    def test_install_custom_duplicate_url_rejected(self, _mock):
        self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Server", "url": "https://mcp.dup.com", "auth_type": "api_key"},
            format="json",
        )
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Server Again", "url": "https://mcp.dup.com", "auth_type": "api_key"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.mcp_store.backend.presentation.views.is_url_allowed", return_value=(False, "Private IP"))
    def test_install_custom_ssrf_blocked(self, _mock):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Evil", "url": "http://192.168.1.1/mcp", "auth_type": "api_key"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.mcp_store.backend.presentation.views.is_url_allowed", return_value=(False, "Local/metadata host"))
    def test_install_custom_oauth_ssrf_blocked(self, _mock):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={
                "name": "Evil OAuth",
                "url": "http://169.254.169.254/mcp",
                "auth_type": "oauth",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @ALLOW_URL
    def test_installation_name_field(self, _mock):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Custom Name", "url": "https://mcp.named.com", "auth_type": "api_key"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["display_name"] == "Custom Name"
        assert response.json()["name"] == "Custom Name"

    @ALLOW_URL
    def test_install_custom_accepts_posthog_code_install_source(self, _mock):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={
                "name": "Code Server",
                "url": "https://mcp.code.com",
                "auth_type": "api_key",
                "install_source": "posthog-code",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_install_custom_rejects_invalid_posthog_code_callback_url(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={
                "name": "Evil",
                "url": "https://mcp.example.com",
                "auth_type": "api_key",
                "install_source": "posthog-code",
                "posthog_code_callback_url": "https://evil.com/steal",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @ALLOW_URL
    def test_install_custom_accepts_posthog_code_callback_url(self, _mock):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={
                "name": "Code Server",
                "url": "https://mcp.code2.com",
                "auth_type": "api_key",
                "install_source": "posthog-code",
                "posthog_code_callback_url": "posthog-code://oauth/callback",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED


class TestOAuthCallback(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def _create_template(self, **kwargs) -> MCPServerTemplate:
        defaults = {
            "name": "Test Template",
            "url": "https://mcp.example.com",
            "auth_type": "oauth",
            "is_active": True,
            "oauth_metadata": {
                "issuer": "https://auth.example.com",
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
                "registration_endpoint": "https://auth.example.com/register",
            },
            "oauth_credentials": {"client_id": "shared-client-id"},
        }
        defaults.update(kwargs)
        return MCPServerTemplate.objects.create(**defaults)

    def _create_installation(self, template: MCPServerTemplate | None = None, **kwargs) -> MCPServerInstallation:
        defaults = {
            "team": self.team,
            "user": self.user,
            "url": "https://mcp.example.com",
            "display_name": "Test",
            "auth_type": "oauth",
            "template": template,
        }
        # If not template-backed, cache OAuth metadata + dcr client id on the installation itself
        if template is None:
            defaults.setdefault(
                "oauth_metadata",
                {
                    "issuer": "https://auth.example.com",
                    "authorization_endpoint": "https://auth.example.com/authorize",
                    "token_endpoint": "https://auth.example.com/token",
                    "registration_endpoint": "https://auth.example.com/register",
                },
            )
            defaults.setdefault("oauth_issuer_url", "https://auth.example.com")
            defaults.setdefault(
                "sensitive_configuration",
                {"dcr_client_id": "dcr-client-id", "dcr_is_user_provided": False},
            )
        defaults.update(kwargs)
        return MCPServerInstallation.objects.create(**defaults)

    def _create_oauth_state(
        self,
        installation,
        state_token,
        pkce_verifier="",
        install_source="posthog",
        posthog_code_callback_url="",
        *,
        template=None,
        created_by=None,
    ):
        from datetime import timedelta

        from django.utils import timezone

        token_hash = hashlib.sha256(state_token.encode("utf-8")).hexdigest()
        return MCPOAuthState.objects.create(
            token_hash=token_hash,
            installation=installation,
            team=self.team,
            template=template,
            pkce_verifier=pkce_verifier,
            install_source=install_source,
            posthog_code_callback_url=posthog_code_callback_url,
            expires_at=timezone.now() + timedelta(seconds=600),
            created_by=created_by if created_by is not None else self.user,
        )

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_dcr_path_used_when_pkce_verifier_present(self, mock_post, _allow):
        installation = self._create_installation()

        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "tok_dcr", "token_type": "bearer"}

        state_token = "test-state-token-dcr"
        self._create_oauth_state(installation, state_token, pkce_verifier="test-pkce-verifier")

        response = self.client.get(
            "/api/mcp_store/oauth_redirect/",
            {"state": state_token, "code": "auth-code"},
        )

        assert response.status_code == 302
        mock_post.assert_called_once()
        assert mock_post.call_args[0][0] == "https://auth.example.com/token"
        assert mock_post.call_args[1]["data"]["code_verifier"] == "test-pkce-verifier"

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_oauth_redirect_uses_posthog_code_callback_url(self, mock_post, _allow):
        installation = self._create_installation()

        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "tok", "token_type": "bearer"}

        callback_url = "posthog-code://oauth/callback"
        state_token = "test-posthog-code-state"
        self._create_oauth_state(
            installation,
            state_token,
            pkce_verifier="test-verifier",
            install_source="posthog-code",
            posthog_code_callback_url=callback_url,
        )

        response = self.client.get(
            "/api/mcp_store/oauth_redirect/",
            {"state": state_token, "code": "auth-code"},
        )

        assert response.status_code == 302
        location = response["Location"]
        assert location.startswith("posthog-code://oauth/callback?")
        assert "status=success" in location

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_oauth_redirect_posthog_code_error_includes_error_param(self, mock_post, _allow):
        installation = self._create_installation()

        callback_url = "posthog-code://oauth/callback"
        state_token = "test-posthog-code-error"
        self._create_oauth_state(
            installation, state_token, install_source="posthog-code", posthog_code_callback_url=callback_url
        )

        response = self.client.get(
            "/api/mcp_store/oauth_redirect/",
            {"state": state_token, "error": "access_denied"},
        )

        assert response.status_code == 302
        location = response["Location"]
        assert location.startswith("posthog-code://oauth/callback?")
        assert "status=error" in location
        assert "error=cancelled" in location

    @patch("products.mcp_store.backend.presentation.views.is_dev_mode", return_value=False)
    def test_callback_rejects_state_for_anonymous_consumer(self, _is_dev):
        """State in an unauthenticated browser must return 400.

        If an OAuth state is handled by a browser where no user is logged in,
        it must not be accepted, preventing state/token theft via phishing."""
        attacker_install = self._create_installation(display_name="Attacker")
        state_token = "attacker-state-token"
        self._create_oauth_state(attacker_install, state_token, pkce_verifier="v")

        victim_client = APIClient()  # not logged in
        response = victim_client.get(
            "/api/mcp_store/oauth_redirect/",
            {"state": state_token, "code": "victim-auth-code"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

        row = MCPOAuthState.objects.get(token_hash=hashlib.sha256(state_token.encode("utf-8")).hexdigest())
        assert row.consumed_at is None
        attacker_install.refresh_from_db()
        assert not (attacker_install.sensitive_configuration or {}).get("access_token")

    @patch("products.mcp_store.backend.presentation.views.is_dev_mode", return_value=True)
    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_callback_rejects_anonymous_posthog_consumer_in_dev(self, mock_post, _allow, _is_dev):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "tok", "token_type": "bearer"}

        installation = self._create_installation()
        state_token = "anonymous-posthog-dev-callback"
        self._create_oauth_state(installation, state_token, pkce_verifier="v", install_source="posthog")

        browser_client = APIClient()
        response = browser_client.get(
            "/api/mcp_store/oauth_redirect/",
            {"state": state_token, "code": "code"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_post.assert_not_called()
        row = MCPOAuthState.objects.get(token_hash=hashlib.sha256(state_token.encode("utf-8")).hexdigest())
        assert row.consumed_at is None
        installation.refresh_from_db()
        assert not (installation.sensitive_configuration or {}).get("access_token")

    @patch("products.mcp_store.backend.presentation.views.is_dev_mode", return_value=True)
    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_callback_accepts_anonymous_consumer_in_dev(self, mock_post, _allow, _is_dev):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "tok", "token_type": "bearer"}

        installation = self._create_installation()
        state_token = "anonymous-dev-callback"
        callback_url = "http://localhost:8238/mcp-oauth-complete"
        self._create_oauth_state(
            installation,
            state_token,
            pkce_verifier="v",
            install_source="posthog-code",
            posthog_code_callback_url=callback_url,
        )

        browser_client = APIClient()
        response = browser_client.get(
            "/api/mcp_store/oauth_redirect/",
            {"state": state_token, "code": "code"},
        )

        assert response.status_code == 302
        assert response["Location"].startswith(f"{callback_url}?")
        assert "status=success" in response["Location"]
        installation.refresh_from_db()
        assert installation.sensitive_configuration["access_token"] == "tok"

    @patch("products.mcp_store.backend.presentation.views.is_dev_mode", return_value=True)
    def test_callback_rejects_state_for_different_authenticated_user(self, _is_dev):
        """State created by user A cannot be consumed by user B in the same browser.

        Covers the scenario where the victim IS logged into PostHog but as a
        different account than the attacker who created the state row.
        """
        from posthog.models import User

        attacker_install = self._create_installation(display_name="Attacker")
        state_token = "cross-user-state"
        self._create_oauth_state(attacker_install, state_token, pkce_verifier="v", created_by=self.user)

        victim_user = User.objects.create_and_join(self.organization, "victim@example.com", "password")
        victim_client = APIClient()
        victim_client.force_login(victim_user)
        response = victim_client.get(
            "/api/mcp_store/oauth_redirect/",
            {"state": state_token, "error": "access_denied"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

        row = MCPOAuthState.objects.get(token_hash=hashlib.sha256(state_token.encode("utf-8")).hexdigest())
        assert row.consumed_at is None

    def test_callback_rejects_state_missing_created_by(self):
        """Defense in depth: legacy rows with NULL created_by cannot be consumed.

        Covers pre-fix state rows that might still exist in the DB at deploy
        time, and any future code path that forgets to populate created_by.
        """
        from datetime import timedelta

        from django.utils import timezone

        installation = self._create_installation()
        state_token = "orphan-state"
        MCPOAuthState.objects.create(
            token_hash=hashlib.sha256(state_token.encode("utf-8")).hexdigest(),
            installation=installation,
            team=self.team,
            pkce_verifier="v",
            expires_at=timezone.now() + timedelta(seconds=600),
            created_by=None,
        )

        response = self.client.get(
            "/api/mcp_store/oauth_redirect/",
            {"state": state_token, "code": "code"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_callback_happy_path_same_user(self, mock_post, _allow):
        """Positive control: callback authenticated as the same user -> success."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "tok", "token_type": "bearer"}

        installation = self._create_installation()
        state_token = "happy-path"
        self._create_oauth_state(installation, state_token, pkce_verifier="v")

        response = self.client.get(
            "/api/mcp_store/oauth_redirect/",
            {"state": state_token, "code": "code"},
        )
        assert response.status_code == 302
        installation.refresh_from_db()
        assert installation.sensitive_configuration["access_token"] == "tok"

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_callback_happy_path_cross_client_same_user(self, mock_post, _allow):
        """posthog-code scenario: initiate and callback happen in different HTTP clients.

        The CLI calls install_custom from its own process (no browser session),
        then opens the authorize URL in the user's default browser. The browser's
        session is not the CLI's session — but both authenticate as the same User,
        and user-binding passes.
        """
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "tok", "token_type": "bearer"}

        installation = self._create_installation()
        state_token = "cross-client"
        self._create_oauth_state(installation, state_token, pkce_verifier="v")

        browser_client = APIClient()
        browser_client.force_login(self.user)
        response = browser_client.get(
            "/api/mcp_store/oauth_redirect/",
            {"state": state_token, "code": "code"},
        )
        assert response.status_code == 302
        installation.refresh_from_db()
        assert installation.sensitive_configuration["access_token"] == "tok"

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_consumed_state_rejects_replay(self, mock_post, _allow):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "tok", "token_type": "bearer"}

        installation = self._create_installation()
        state_token = "one-shot"
        self._create_oauth_state(installation, state_token, pkce_verifier="v")

        first = self.client.get("/api/mcp_store/oauth_redirect/", {"state": state_token, "code": "c1"})
        assert first.status_code == 302

        second = self.client.get("/api/mcp_store/oauth_redirect/", {"state": state_token, "code": "c2"})
        assert second.status_code == status.HTTP_400_BAD_REQUEST

    def test_session_cookie_samesite_is_compatible_with_oauth_redirect(self):
        """Pin the deployment invariant the fix depends on.

        If SESSION_COOKIE_SAMESITE is 'Strict', the session cookie will not
        be sent on the top-level cross-site GET from the OAuth provider,
        SessionAuthentication will see AnonymousUser on the callback, and
        every legitimate flow will 400. 'Lax' (Django default) or 'None' work.
        """
        from django.conf import settings

        assert settings.SESSION_COOKIE_SAMESITE in ("Lax", "None")

    @ALLOW_URL
    def test_authorize_endpoint_populates_created_by(self, _allow):
        """The GET /authorize/ path must also stamp created_by, not just install_custom."""
        template = self._create_template(url="https://mcp.example.com")
        # Pre-existing installation pointing at this template
        MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            template=template,
            url=template.url,
            display_name="Pre",
            auth_type="oauth",
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/mcp_server_installations/authorize/",
            {"template_id": str(template.id)},
        )
        assert response.status_code == 302

        state_token = parse_qs(urlparse(response["Location"]).query)["state"][0]
        row = MCPOAuthState.objects.get(token_hash=hashlib.sha256(state_token.encode("utf-8")).hexdigest())
        assert row.created_by_id == self.user.id
        assert row.template_id == template.id

    @ALLOW_URL
    @patch("products.mcp_store.backend.presentation.views.discover_oauth_metadata")
    @patch(
        "products.mcp_store.backend.presentation.views.register_dcr_client",
        return_value=("dcr-client-id", None, "none"),
    )
    def test_install_custom_populates_created_by(self, _mock_dcr, mock_discover, _allow):
        """install_custom path must stamp created_by on the MCPOAuthState row."""
        mock_discover.return_value = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "registration_endpoint": "https://auth.example.com/register",
        }

        resp = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "srv", "url": "https://mcp.example.com/mcp", "auth_type": "oauth"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.content

        state_token = parse_qs(urlparse(resp.json()["redirect_url"]).query)["state"][0]
        row = MCPOAuthState.objects.get(token_hash=hashlib.sha256(state_token.encode("utf-8")).hexdigest())
        assert row.created_by_id == self.user.id


class TestOAuthIssuerSpoofingProtection(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def _create_template(self, **overrides) -> MCPServerTemplate:
        # Use a unique URL per call to avoid collisions with seeded curated templates
        import uuid as _uuid

        defaults = {
            "name": "Test Template",
            "url": f"https://mcp.test-{_uuid.uuid4().hex[:8]}.example.com/mcp",
            "auth_type": "oauth",
            "is_active": True,
            "oauth_metadata": {
                "authorization_endpoint": "https://auth.test.example.com/authorize",
                "token_endpoint": "https://auth.test.example.com/token",
            },
            "oauth_credentials": {"client_id": "test-client-id"},
        }
        defaults.update(overrides)
        return MCPServerTemplate.objects.create(**defaults)

    @ALLOW_URL
    @patch("products.mcp_store.backend.presentation.views.discover_oauth_metadata")
    def test_spoofed_issuer_fails_and_no_state_persisted(self, mock_discover, _allow):
        mock_discover.side_effect = ValueError("Issuer mismatch in authorization server metadata")

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Evil", "url": "https://evil.com/mcp", "auth_type": "oauth"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not MCPServerInstallation.objects.filter(url="https://evil.com/mcp").exists()

    @ALLOW_URL
    @patch("products.mcp_store.backend.presentation.views.register_dcr_client")
    @patch("products.mcp_store.backend.presentation.views.discover_oauth_metadata")
    def test_installation_caches_discovered_metadata_per_user(self, mock_discover, mock_dcr, _allow):
        """Each custom install gets its own cached metadata + DCR client id.

        Installing the same URL twice (by different users, or the same user after
        uninstall) must not share DCR client creds — each installation is its own
        quarantine unit.
        """
        mock_discover.return_value = {
            "issuer": "https://auth.legit.com",
            "authorization_endpoint": "https://auth.legit.com/authorize",
            "token_endpoint": "https://auth.legit.com/token",
            "registration_endpoint": "https://auth.legit.com/register",
        }
        mock_dcr.return_value = ("per-user-dcr-client", None, "none")

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Legit", "url": "https://mcp.legit.com/mcp", "auth_type": "oauth"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert urlparse(response.json()["redirect_url"]).netloc == "auth.legit.com"

        installation = MCPServerInstallation.objects.get(url="https://mcp.legit.com/mcp", user=self.user)
        assert installation.oauth_metadata["authorization_endpoint"] == "https://auth.legit.com/authorize"
        assert installation.sensitive_configuration["dcr_client_id"] == "per-user-dcr-client"
        assert installation.sensitive_configuration["dcr_token_endpoint_auth_method"] == "none"
        # EncryptedJSONField stringifies leaf values on round-trip; accept either bool or str.
        assert installation.sensitive_configuration["dcr_is_user_provided"] in (False, "False")

    @ALLOW_URL
    @patch("products.mcp_store.backend.presentation.views.register_dcr_client")
    @patch("products.mcp_store.backend.presentation.views.discover_oauth_metadata")
    def test_install_custom_persists_dcr_minted_client_secret(self, mock_discover, mock_dcr, _allow):
        """When the auth server registers a confidential client during DCR, persist the secret.

        Some providers (e.g. Supabase) ignore ``token_endpoint_auth_method=none``
        and register a confidential client anyway, returning a ``client_secret``
        that the token endpoint then requires. Dropping it makes the subsequent
        token exchange fail with 422 ``Required parameter: client_secret``.
        """
        mock_discover.return_value = {
            "issuer": "https://auth.legit.com",
            "authorization_endpoint": "https://auth.legit.com/authorize",
            "token_endpoint": "https://auth.legit.com/token",
            "registration_endpoint": "https://auth.legit.com/register",
        }
        mock_dcr.return_value = ("dcr-minted-client", "dcr-minted-secret", "client_secret_post")

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Legit", "url": "https://mcp.legit.com/mcp", "auth_type": "oauth"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        installation = MCPServerInstallation.objects.get(url="https://mcp.legit.com/mcp", user=self.user)
        sensitive = installation.sensitive_configuration
        assert sensitive["dcr_client_id"] == "dcr-minted-client"
        assert sensitive["dcr_client_secret"] == "dcr-minted-secret"
        assert sensitive["dcr_token_endpoint_auth_method"] == "client_secret_post"
        assert sensitive["dcr_is_user_provided"] in (False, "False")

    @ALLOW_URL
    @patch("products.mcp_store.backend.presentation.views.register_dcr_client")
    @patch("products.mcp_store.backend.presentation.views.discover_oauth_metadata")
    def test_install_custom_with_user_supplied_creds_skips_dcr(self, mock_discover, mock_dcr, _allow):
        """If the user provides client_id + client_secret we trust them and skip DCR."""
        mock_discover.return_value = {
            "issuer": "https://auth.legit.com",
            "authorization_endpoint": "https://auth.legit.com/authorize",
            "token_endpoint": "https://auth.legit.com/token",
            "registration_endpoint": "https://auth.legit.com/register",
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={
                "name": "Legit",
                "url": "https://mcp.legit.com/mcp",
                "auth_type": "oauth",
                "client_id": "user-supplied-client-id",
                "client_secret": "user-supplied-secret",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        mock_dcr.assert_not_called()

        installation = MCPServerInstallation.objects.get(url="https://mcp.legit.com/mcp", user=self.user)
        sensitive = installation.sensitive_configuration
        assert sensitive["dcr_client_id"] == "user-supplied-client-id"
        assert sensitive["dcr_client_secret"] == "user-supplied-secret"
        assert sensitive["dcr_token_endpoint_auth_method"] == "client_secret_basic"
        # EncryptedJSONField stringifies leaf values on round-trip; accept either bool or str.
        assert sensitive["dcr_is_user_provided"] in (True, "True")

        params = parse_qs(urlparse(response.json()["redirect_url"]).query)
        assert params["client_id"][0] == "user-supplied-client-id"

    @ALLOW_URL
    @patch("products.mcp_store.backend.presentation.views.register_dcr_client")
    @patch("products.mcp_store.backend.presentation.views.discover_oauth_metadata")
    def test_install_custom_with_user_supplied_creds_rejects_unsupported_auth_method(
        self, mock_discover, mock_dcr, _allow
    ):
        mock_discover.return_value = {
            "issuer": "https://auth.legit.com",
            "authorization_endpoint": "https://auth.legit.com/authorize",
            "token_endpoint": "https://auth.legit.com/token",
            "registration_endpoint": "https://auth.legit.com/register",
            "token_endpoint_auth_methods_supported": ["private_key_jwt"],
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={
                "name": "Legit",
                "url": "https://mcp.legit.com/mcp",
                "auth_type": "oauth",
                "client_id": "user-supplied-client-id",
                "client_secret": "user-supplied-secret",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "OAuth token endpoint auth method is not supported."
        assert not MCPServerInstallation.objects.filter(url="https://mcp.legit.com/mcp", user=self.user).exists()
        mock_dcr.assert_not_called()

    @ALLOW_URL
    @patch("products.mcp_store.backend.presentation.views.register_dcr_client")
    @patch("products.mcp_store.backend.presentation.views.discover_oauth_metadata")
    def test_install_custom_discards_secret_when_client_id_missing(self, mock_discover, mock_dcr, _allow):
        """A stray client_secret without a client_id falls back to DCR and the secret is dropped.

        Storing it would pair a DCR-minted client_id with an unrelated secret —
        token exchange would fail in confusing ways.
        """
        mock_discover.return_value = {
            "issuer": "https://auth.legit.com",
            "authorization_endpoint": "https://auth.legit.com/authorize",
            "token_endpoint": "https://auth.legit.com/token",
            "registration_endpoint": "https://auth.legit.com/register",
        }
        mock_dcr.return_value = ("dcr-minted-client", None, "none")

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={
                "name": "Legit",
                "url": "https://mcp.legit.com/mcp",
                "auth_type": "oauth",
                "client_secret": "orphan-secret",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        mock_dcr.assert_called_once()

        installation = MCPServerInstallation.objects.get(url="https://mcp.legit.com/mcp", user=self.user)
        sensitive = installation.sensitive_configuration
        assert sensitive["dcr_client_id"] == "dcr-minted-client"
        assert "dcr_client_secret" not in sensitive
        assert sensitive["dcr_token_endpoint_auth_method"] == "none"
        assert sensitive["dcr_is_user_provided"] in (False, "False")

    @ALLOW_URL
    @patch(
        "products.mcp_store.backend.presentation.views.register_dcr_client",
        return_value=("new-dcr-client", None, "none"),
    )
    @patch("products.mcp_store.backend.presentation.views.discover_oauth_metadata")
    def test_reinstall_clears_stale_tokens_and_flags_reauth(self, mock_discover, _mock_dcr, _allow):
        """Re-running install_custom swaps the DCR client; stale tokens from the old client must be cleared.

        Otherwise the UI + agent would see the installation as still connected
        (via the old access_token) and the first refresh would fail with
        invalid_client against the new DCR client.
        """
        mock_discover.return_value = {
            "issuer": "https://auth.legit.com",
            "authorization_endpoint": "https://auth.legit.com/authorize",
            "token_endpoint": "https://auth.legit.com/token",
            "registration_endpoint": "https://auth.legit.com/register",
        }

        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            url="https://mcp.legit.com/mcp",
            display_name="Legit",
            auth_type="oauth",
            oauth_issuer_url="https://auth.legit.com",
            oauth_metadata={
                "authorization_endpoint": "https://auth.legit.com/authorize",
                "token_endpoint": "https://auth.legit.com/token",
            },
            sensitive_configuration={
                "dcr_client_id": "old-dcr-client",
                "dcr_is_user_provided": False,
                "access_token": "old-access-token",
                "refresh_token": "old-refresh-token",
                "token_retrieved_at": 1_700_000_000,
                "expires_in": 3600,
            },
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
            data={"name": "Legit", "url": "https://mcp.legit.com/mcp", "auth_type": "oauth"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        installation.refresh_from_db()
        sensitive = installation.sensitive_configuration
        assert sensitive["dcr_client_id"] == "new-dcr-client"
        assert sensitive["dcr_token_endpoint_auth_method"] == "none"
        assert sensitive["needs_reauth"] in (True, "True")
        for stale_key in ("access_token", "refresh_token", "token_retrieved_at", "expires_in"):
            assert stale_key not in sensitive, f"{stale_key} should have been cleared on re-install"

    @ALLOW_URL
    @patch("products.mcp_store.backend.presentation.views.discover_oauth_metadata")
    def test_authorize_reuses_cached_installation_metadata(self, mock_discover, _allow):
        """Re-authorizing an existing custom install must not re-run discovery or DCR."""
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            url="https://mcp.example.com",
            display_name="Test",
            auth_type="oauth",
            oauth_issuer_url="https://auth.example.com",
            oauth_metadata={
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
                "resource": "https://mcp.example.com/",
                "scopes_supported": ["admin", "read"],
                "resource_scopes_supported": ["read"],
            },
            sensitive_configuration={"dcr_client_id": "existing-client-id", "dcr_is_user_provided": False},
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/mcp_server_installations/authorize/",
            {"installation_id": str(installation.id)},
        )

        assert response.status_code == 302
        assert urlparse(response["Location"]).netloc == "auth.example.com"
        mock_discover.assert_not_called()
        params = parse_qs(urlparse(response["Location"]).query)
        assert params["client_id"][0] == "existing-client-id"
        assert params["resource"][0] == "https://mcp.example.com/"
        assert params["scope"][0] == "read"

    @ALLOW_URL
    def test_authorize_uses_opaque_state_token(self, _allow):
        template = self._create_template()
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            template=template,
            url=template.url,
            auth_type="oauth",
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/mcp_server_installations/authorize/",
            {"template_id": str(template.id)},
        )

        assert response.status_code == 302
        parsed = urlparse(response["Location"])
        params = parse_qs(parsed.query)
        state_token = params["state"][0]
        assert "template_id=" not in state_token
        assert "team_id=" not in state_token

        expected_hash = hashlib.sha256(state_token.encode("utf-8")).hexdigest()
        assert MCPOAuthState.objects.filter(
            token_hash=expected_hash,
            installation=installation,
            team=self.team,
            template=template,
            consumed_at__isnull=True,
        ).exists()

    @ALLOW_URL
    def test_public_oauth_redirect_consumes_state_once(self, _allow):
        template = self._create_template()
        MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            template=template,
            url=template.url,
            auth_type="oauth",
        )

        authorize_response = self.client.get(
            f"/api/environments/{self.team.id}/mcp_server_installations/authorize/",
            {"template_id": str(template.id)},
        )
        state_token = parse_qs(urlparse(authorize_response["Location"]).query)["state"][0]

        first_callback = self.client.get(
            "/api/mcp_store/oauth_redirect/", {"state": state_token, "error": "access_denied"}
        )
        assert first_callback.status_code == 302

        second_callback = self.client.get(
            "/api/mcp_store/oauth_redirect/", {"state": state_token, "error": "access_denied"}
        )
        assert second_callback.status_code == status.HTTP_400_BAD_REQUEST


class TestMCPAuthorizePosthogCodeResponse(APIBaseTest):
    def _create_template(self) -> MCPServerTemplate:
        return MCPServerTemplate.objects.create(
            name="Test Template",
            url="https://mcp.test.example.com/mcp",
            auth_type="oauth",
            is_active=True,
            oauth_metadata={
                "authorization_endpoint": "https://auth.test.example.com/authorize",
                "token_endpoint": "https://auth.test.example.com/token",
            },
            oauth_credentials={"client_id": "test-client-id"},
        )

    @ALLOW_URL
    @patch("products.mcp_store.backend.presentation.views.discover_oauth_metadata")
    def test_authorize_returns_redirect_url_for_custom_installation(self, mock_discover, _allow):
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            url="https://mcp.example.com",
            display_name="Test",
            auth_type="oauth",
            oauth_issuer_url="https://auth.example.com",
            oauth_metadata={
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
            },
            sensitive_configuration={"dcr_client_id": "existing-client-id", "dcr_is_user_provided": False},
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/mcp_server_installations/authorize/",
            {
                "installation_id": str(installation.id),
                "install_source": "posthog-code",
                "posthog_code_callback_url": "posthog-code://oauth/callback",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert "Location" not in response
        redirect_url = response.json()["redirect_url"]
        assert urlparse(redirect_url).netloc == "auth.example.com"
        mock_discover.assert_not_called()
        params = parse_qs(urlparse(redirect_url).query)
        assert params["client_id"][0] == "existing-client-id"

    @ALLOW_URL
    def test_authorize_returns_redirect_url_for_template_installation(self, _allow):
        template = self._create_template()
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            template=template,
            url=template.url,
            auth_type="oauth",
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/mcp_server_installations/authorize/",
            {
                "installation_id": str(installation.id),
                "install_source": "posthog-code",
                "posthog_code_callback_url": "posthog-code://oauth/callback",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert "Location" not in response
        redirect_url = response.json()["redirect_url"]
        assert urlparse(redirect_url).netloc == "auth.test.example.com"
        params = parse_qs(urlparse(redirect_url).query)
        assert params["client_id"][0] == "test-client-id"


class TestInstallTemplateAPI(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def _template(self, **overrides) -> MCPServerTemplate:
        import uuid as _uuid

        defaults = {
            "name": f"Template-{_uuid.uuid4().hex[:6]}",
            "url": f"https://mcp-{_uuid.uuid4().hex[:8]}.test.example.com/mcp",
            "auth_type": "oauth",
            "is_active": True,
            "oauth_metadata": {
                "authorization_endpoint": "https://auth.test.example.com/authorize",
                "token_endpoint": "https://auth.test.example.com/token",
            },
            "oauth_credentials": {"client_id": "template-client-id"},
        }
        defaults.update(overrides)
        return MCPServerTemplate.objects.create(**defaults)

    def test_install_template_oauth_returns_redirect_url(self):
        template = self._template()

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_template/",
            data={"template_id": str(template.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        redirect_url = response.json()["redirect_url"]
        assert urlparse(redirect_url).netloc == "auth.test.example.com"
        params = parse_qs(urlparse(redirect_url).query)
        assert params["client_id"][0] == "template-client-id"

        installation = MCPServerInstallation.objects.get(url=template.url, user=self.user)
        assert installation.template_id == template.id

    def test_install_template_api_key_stores_key_and_returns_installation(self):
        template = self._template(auth_type="api_key", oauth_credentials={}, oauth_metadata={})

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_template/",
            data={"template_id": str(template.id), "api_key": "sk-template"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        body = response.json()
        assert body["template_id"] == str(template.id)

        installation = MCPServerInstallation.objects.get(id=body["id"])
        assert installation.sensitive_configuration["api_key"] == "sk-template"

    def test_install_template_api_key_requires_key(self):
        template = self._template(auth_type="api_key", oauth_credentials={}, oauth_metadata={})

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_template/",
            data={"template_id": str(template.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_install_template_rejects_inactive_template(self):
        template = self._template(is_active=False)

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_template/",
            data={"template_id": str(template.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_install_template_shared_creds_without_oauth_metadata_returns_400(self):
        # Shared-creds templates require admin-seeded metadata. (DCR templates
        # don't — they discover at install time; see below.)
        template = self._template(oauth_metadata={})

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_template/",
            data={"template_id": str(template.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch(
        "products.mcp_store.backend.presentation.views.register_dcr_client",
        return_value=("minted-per-user-client", None, "none"),
    )
    @patch(
        "products.mcp_store.backend.presentation.views.discover_oauth_metadata",
        return_value={
            "authorization_endpoint": "https://auth.discovered.example.com/authorize",
            "token_endpoint": "https://auth.discovered.example.com/token",
            "registration_endpoint": "https://auth.discovered.example.com/register",
        },
    )
    def test_install_template_dcr_discovers_metadata_and_mints_per_user_client(self, mock_discover, mock_register):
        # DCR template with NO admin-seeded metadata: the install flow discovers
        # OAuth endpoints at install time (same as the custom-install flow).
        # The discovered metadata is cached on the installation, never on the
        # template — a first-installer can't poison template state for other users.
        template = self._template(oauth_credentials={}, oauth_metadata={})

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_template/",
            data={"template_id": str(template.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert mock_discover.called
        assert mock_register.called

        redirect_url = response.json()["redirect_url"]
        assert urlparse(redirect_url).netloc == "auth.discovered.example.com"
        params = parse_qs(urlparse(redirect_url).query)
        assert params["client_id"][0] == "minted-per-user-client"

        installation = MCPServerInstallation.objects.get(url=template.url, user=self.user)
        sensitive = installation.sensitive_configuration or {}
        assert sensitive["dcr_client_id"] == "minted-per-user-client"
        assert sensitive["dcr_token_endpoint_auth_method"] == "none"
        # Discovered metadata is cached on the installation, not written back to the template.
        assert installation.oauth_metadata["token_endpoint"] == "https://auth.discovered.example.com/token"
        template.refresh_from_db()
        assert template.oauth_metadata == {}

    @patch(
        "products.mcp_store.backend.presentation.views.discover_oauth_metadata",
        side_effect=RuntimeError("discovery network error"),
    )
    def test_install_template_dcr_discovery_failure_returns_400_and_cleans_up(self, _mock):
        template = self._template(oauth_credentials={}, oauth_metadata={})

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_template/",
            data={"template_id": str(template.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not MCPServerInstallation.objects.filter(url=template.url, user=self.user).exists()

    @patch(
        "products.mcp_store.backend.presentation.views.register_dcr_client",
        side_effect=ValueError("dcr not supported"),
    )
    @patch(
        "products.mcp_store.backend.presentation.views.discover_oauth_metadata",
        return_value={
            "authorization_endpoint": "https://auth.discovered.example.com/authorize",
            "token_endpoint": "https://auth.discovered.example.com/token",
            "registration_endpoint": "https://auth.discovered.example.com/register",
        },
    )
    def test_install_template_dcr_not_supported_returns_400_and_cleans_up(self, _discover, _register):
        template = self._template(oauth_credentials={}, oauth_metadata={})

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/install_template/",
            data={"template_id": str(template.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # A half-created installation should not linger after DCR failure.
        assert not MCPServerInstallation.objects.filter(url=template.url, user=self.user).exists()


class TestInstallationToolsAPI(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def _installation(self, **kwargs) -> MCPServerInstallation:
        import uuid as _uuid

        defaults = {
            "team": self.team,
            "user": self.user,
            "url": f"https://mcp-{_uuid.uuid4().hex[:8]}.example.com/mcp",
            "display_name": "Test",
            "auth_type": "api_key",
            "sensitive_configuration": {"api_key": "sk"},
        }
        defaults.update(kwargs)
        return MCPServerInstallation.objects.create(**defaults)

    def _tool(self, installation, name, approval_state="needs_approval", removed=False):
        from django.utils import timezone

        from products.mcp_store.backend.models import MCPServerInstallationTool

        return MCPServerInstallationTool.objects.create(
            installation=installation,
            tool_name=name,
            approval_state=approval_state,
            last_seen_at=timezone.now(),
            removed_at=timezone.now() if removed else None,
        )

    def test_list_tools_returns_only_active_by_default(self):
        installation = self._installation()
        self._tool(installation, "alpha")
        self._tool(installation, "gone", removed=True)

        response = self.client.get(
            f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/tools/"
        )
        assert response.status_code == status.HTTP_200_OK
        names = [t["tool_name"] for t in response.json()["results"]]
        assert names == ["alpha"]

    def test_list_tools_include_removed_query_param(self):
        installation = self._installation()
        self._tool(installation, "alpha")
        self._tool(installation, "gone", removed=True)

        response = self.client.get(
            f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/tools/",
            {"include_removed": "1"},
        )
        assert response.status_code == status.HTTP_200_OK
        names = [t["tool_name"] for t in response.json()["results"]]
        assert set(names) == {"alpha", "gone"}

    def test_update_tool_approval_state(self):
        installation = self._installation()
        tool = self._tool(installation, "alpha", approval_state="needs_approval")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/tools/{tool.tool_name}/",
            data={"approval_state": "approved"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["approval_state"] == "approved"
        tool.refresh_from_db()
        assert tool.approval_state == "approved"

    def test_update_tool_approval_rejects_invalid_state(self):
        installation = self._installation()
        self._tool(installation, "alpha")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/tools/alpha/",
            data={"approval_state": "bogus"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_missing_tool_returns_404(self):
        installation = self._installation()

        response = self.client.patch(
            f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/tools/ghost/",
            data={"approval_state": "approved"},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("products.mcp_store.backend.presentation.views.sync_installation_tools")
    def test_refresh_tools_invokes_sync_and_returns_active(self, mock_sync):
        installation = self._installation()
        existing = self._tool(installation, "kept")

        def _stub(_inst):
            # Simulate a sync that discovered one new tool and left the existing one.
            self._tool(installation, "freshly-discovered")
            return []

        mock_sync.side_effect = _stub

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/tools/refresh/"
        )
        assert response.status_code == status.HTTP_200_OK
        mock_sync.assert_called_once()
        names = {t["tool_name"] for t in response.json()["results"]}
        assert {existing.tool_name, "freshly-discovered"} == names

    def test_refresh_tools_rejected_for_disabled_installation(self):
        installation = self._installation(is_enabled=False)

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/tools/refresh/"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestInstallDispatchesToolSync(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    @ALLOW_URL
    @patch("products.mcp_store.backend.presentation.views.sync_installation_tools_task")
    def test_install_custom_api_key_dispatches_background_sync(self, mock_task, _allow):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/environments/{self.team.id}/mcp_server_installations/install_custom/",
                data={
                    "name": "My API Server",
                    "url": "https://mcp.custom-sync.com",
                    "auth_type": "api_key",
                    "api_key": "sk-test",
                },
                format="json",
            )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        installation_id = response.json()["id"]
        mock_task.delay.assert_called_once_with(installation_id)

    @patch("products.mcp_store.backend.presentation.views.sync_installation_tools_task")
    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_oauth_redirect_dispatches_background_sync(self, mock_post, _allow, mock_task):
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            url="https://mcp.oauth-sync.example.com",
            display_name="OAuth sync",
            auth_type="oauth",
            oauth_metadata={
                "issuer": "https://auth.example.com",
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
            },
            oauth_issuer_url="https://auth.example.com",
            sensitive_configuration={"dcr_client_id": "dcr-client-id", "dcr_is_user_provided": False},
        )

        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "tok", "token_type": "bearer"}

        state_token = "sync-dispatch-state"
        token_hash = hashlib.sha256(state_token.encode("utf-8")).hexdigest()
        from datetime import timedelta

        from django.utils import timezone

        MCPOAuthState.objects.create(
            token_hash=token_hash,
            installation=installation,
            team=self.team,
            pkce_verifier="verifier",
            install_source="posthog",
            posthog_code_callback_url="",
            expires_at=timezone.now() + timedelta(seconds=600),
            created_by=self.user,
        )

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(
                "/api/mcp_store/oauth_redirect/",
                {"state": state_token, "code": "auth-code"},
            )

        assert response.status_code == 302
        mock_task.delay.assert_called_once_with(str(installation.id))


class TestMCPInstallationScopeAccess(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def _api_url(self, suffix: str = "") -> str:
        base = f"/api/environments/{self.team.id}/mcp_server_installations/"
        return f"{base}{suffix}" if suffix else base

    def _create_installation(self, user=None, scope="personal", **kwargs) -> MCPServerInstallation:
        import uuid as _uuid

        defaults: dict = {
            "team": self.team,
            "user": user or self.user,
            "display_name": f"Server-{_uuid.uuid4().hex[:6]}",
            "url": f"https://mcp.test-{_uuid.uuid4().hex[:8]}.example.com/mcp",
            "auth_type": "api_key",
            "is_enabled": True,
            "scope": scope,
        }
        defaults.update(kwargs)
        return MCPServerInstallation.objects.create(**defaults)

    def test_list_shows_own_personal_and_all_shared(self) -> None:
        from posthog.models import User

        other = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        own_personal = self._create_installation(scope="personal")
        own_shared = self._create_installation(scope="shared")
        other_shared = self._create_installation(user=other, scope="shared")
        self._create_installation(user=other, scope="personal")

        response = self.client.get(self._api_url())
        assert response.status_code == status.HTTP_200_OK
        returned_ids = {r["id"] for r in response.json()["results"]}
        assert returned_ids == {str(own_personal.id), str(own_shared.id), str(other_shared.id)}

    def test_scope_returned_in_serializer(self) -> None:
        self._create_installation(scope="shared")

        response = self.client.get(self._api_url())
        assert response.json()["results"][0]["scope"] == "shared"

    def test_non_owner_cannot_delete_shared(self) -> None:
        from posthog.models import User

        other = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        shared = self._create_installation(user=other, scope="shared")

        response = self.client.delete(self._api_url(f"{shared.id}/"))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert MCPServerInstallation.objects.filter(id=shared.id).exists()

    def test_owner_can_delete_shared(self) -> None:
        shared = self._create_installation(scope="shared")

        response = self.client.delete(self._api_url(f"{shared.id}/"))
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_non_owner_cannot_patch_shared(self) -> None:
        from posthog.models import User

        other = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        shared = self._create_installation(user=other, scope="shared")

        response = self.client.patch(
            self._api_url(f"{shared.id}/"),
            data={"display_name": "Hijacked"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_non_owner_admin_can_delete_shared(self) -> None:
        # Admins may delete another member's shared installation so shared
        # credentials don't become orphaned when the owner leaves the team.
        from posthog.models import User

        self._make_admin()
        other = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        shared = self._create_installation(user=other, scope="shared")

        response = self.client.delete(self._api_url(f"{shared.id}/"))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not MCPServerInstallation.objects.filter(id=shared.id).exists()

    def test_non_owner_admin_still_cannot_patch_shared(self) -> None:
        # The destroy override is delete-only: reconfiguring how the owner's
        # credential is used stays strictly owner-only, even for admins.
        from posthog.models import User

        self._make_admin()
        other = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        shared = self._create_installation(user=other, scope="shared")

        response = self.client.patch(
            self._api_url(f"{shared.id}/"),
            data={"display_name": "Hijacked"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_cannot_delete_another_members_personal(self) -> None:
        # Personal rows behave as before: they aren't even visible to other
        # members, admin or not.
        from posthog.models import User

        self._make_admin()
        other = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        personal = self._create_installation(user=other, scope="personal")

        response = self.client.delete(self._api_url(f"{personal.id}/"))
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert MCPServerInstallation.objects.filter(id=personal.id).exists()

    def test_share_by_owner_admin_flips_scope(self) -> None:
        self._make_admin()
        personal = self._create_installation(scope="personal")

        response = self.client.post(self._api_url(f"{personal.id}/share/"))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["scope"] == "shared"
        personal.refresh_from_db()
        assert personal.scope == "shared"

    def test_share_by_owner_non_admin_forbidden(self) -> None:
        # self.user is a MEMBER by default; sharing carries the same admin
        # gate as creating a shared install outright.
        personal = self._create_installation(scope="personal")

        response = self.client.post(self._api_url(f"{personal.id}/share/"))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        personal.refresh_from_db()
        assert personal.scope == "personal"

    def test_share_by_non_owner_admin_rejected(self) -> None:
        # Another member's personal installation isn't even addressable: the
        # queryset only exposes shared rows and your own, so a non-owner admin
        # gets 404 before the in-action owner check (kept as defense in depth)
        # could 403.
        from posthog.models import User

        self._make_admin()
        other = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        personal = self._create_installation(user=other, scope="personal")

        response = self.client.post(self._api_url(f"{personal.id}/share/"))
        assert response.status_code == status.HTTP_404_NOT_FOUND
        personal.refresh_from_db()
        assert personal.scope == "personal"

    def test_share_conflicts_with_existing_shared_url(self) -> None:
        from posthog.models import User

        self._make_admin()
        other = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        url = "https://mcp.share-conflict.example.com/mcp"
        self._create_installation(user=other, scope="shared", url=url)
        personal = self._create_installation(scope="personal", url=url)

        response = self.client.post(self._api_url(f"{personal.id}/share/"))
        assert response.status_code == status.HTTP_409_CONFLICT
        personal.refresh_from_db()
        assert personal.scope == "personal"

    def test_share_already_shared_returns_400(self) -> None:
        self._make_admin()
        shared = self._create_installation(scope="shared")

        response = self.client.post(self._api_url(f"{shared.id}/share/"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        shared.refresh_from_db()
        assert shared.scope == "shared"

    def test_unshare_by_owner(self) -> None:
        shared = self._create_installation(scope="shared")

        response = self.client.post(self._api_url(f"{shared.id}/unshare/"))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["scope"] == "personal"
        shared.refresh_from_db()
        assert shared.scope == "personal"
        assert shared.user_id == self.user.id

    def test_unshare_by_non_owner_admin_keeps_original_owner(self) -> None:
        from posthog.models import User

        self._make_admin()
        other = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        shared = self._create_installation(user=other, scope="shared")

        response = self.client.post(self._api_url(f"{shared.id}/unshare/"))
        assert response.status_code == status.HTTP_200_OK
        shared.refresh_from_db()
        assert shared.scope == "personal"
        # The row must stay owned by the ORIGINAL owner — an admin unsharing
        # someone else's install must not capture their credential.
        assert shared.user_id == other.id

    def test_unshare_by_non_owner_member_forbidden(self) -> None:
        from posthog.models import User

        other = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        shared = self._create_installation(user=other, scope="shared")

        response = self.client.post(self._api_url(f"{shared.id}/unshare/"))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        shared.refresh_from_db()
        assert shared.scope == "shared"

    def test_unshare_conflicts_with_owner_personal_duplicate(self) -> None:
        url = "https://mcp.unshare-conflict.example.com/mcp"
        self._create_installation(scope="personal", url=url)
        shared = self._create_installation(scope="shared", url=url)

        response = self.client.post(self._api_url(f"{shared.id}/unshare/"))
        assert response.status_code == status.HTTP_409_CONFLICT
        shared.refresh_from_db()
        assert shared.scope == "shared"

    def test_unshare_personal_returns_400(self) -> None:
        personal = self._create_installation(scope="personal")

        response = self.client.post(self._api_url(f"{personal.id}/unshare/"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        personal.refresh_from_db()
        assert personal.scope == "personal"

    def test_is_owner_flag_in_list(self) -> None:
        from posthog.models import User

        other = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        own_personal = self._create_installation(scope="personal")
        own_shared = self._create_installation(scope="shared")
        other_shared = self._create_installation(user=other, scope="shared")

        response = self.client.get(self._api_url())
        assert response.status_code == status.HTTP_200_OK
        by_id = {r["id"]: r for r in response.json()["results"]}
        assert by_id[str(own_personal.id)]["is_owner"] is True
        assert by_id[str(own_shared.id)]["is_owner"] is True
        assert by_id[str(other_shared.id)]["is_owner"] is False

    def test_any_member_can_proxy_shared(self) -> None:
        from unittest.mock import (
            MagicMock,
            patch as mock_patch,
        )

        from posthog.models import User

        other = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        shared = self._create_installation(user=other, scope="shared", sensitive_configuration={"api_key": "k"})

        with mock_patch("products.mcp_store.backend.proxy.is_url_allowed", return_value=(True, None)):
            with mock_patch("products.mcp_store.backend.proxy.httpx.Client") as mock_client_cls:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.headers = {"content-type": "application/json"}
                mock_resp.content = b'{"jsonrpc":"2.0","id":1,"result":{}}'
                mock_client = MagicMock()
                mock_client.build_request.return_value = MagicMock()
                mock_client.send.return_value = mock_resp
                mock_client_cls.return_value = mock_client

                response = self.client.post(
                    self._api_url(f"{shared.id}/proxy/"),
                    data={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
                    format="json",
                )

        assert response.status_code == 200

    def _make_admin(self, user=None) -> None:
        from posthog.models import OrganizationMembership

        membership = (user or self.user).organization_memberships.get(organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

    @ALLOW_URL
    def test_install_custom_shared(self, _mock) -> None:
        self._make_admin()
        response = self.client.post(
            self._api_url("install_custom/"),
            data={
                "name": "Shared Custom",
                "url": "https://mcp.shared-custom.example.com/mcp",
                "auth_type": "api_key",
                "api_key": "key123",
                "scope": "shared",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["scope"] == "shared"

    @ALLOW_URL
    def test_install_custom_shared_requires_admin(self, _mock) -> None:
        # self.user is a MEMBER by default; shared creation must be admin-gated.
        response = self.client.post(
            self._api_url("install_custom/"),
            data={
                "name": "Shared Custom",
                "url": "https://mcp.member-shared.example.com/mcp",
                "auth_type": "api_key",
                "api_key": "key123",
                "scope": "shared",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not MCPServerInstallation.objects.filter(
            url="https://mcp.member-shared.example.com/mcp", scope="shared"
        ).exists()

    def test_install_template_shared_requires_admin(self) -> None:
        template = MCPServerTemplate.objects.create(
            name="Admin Gate Template",
            url="https://mcp.admin-gate.example.com/mcp",
            auth_type="api_key",
            is_active=True,
        )
        response = self.client.post(
            self._api_url("install_template/"),
            data={"template_id": str(template.id), "api_key": "k", "scope": "shared"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not MCPServerInstallation.objects.filter(url=template.url, scope="shared").exists()

    def test_install_template_shared_allowed_for_admin(self) -> None:
        self._make_admin()
        template = MCPServerTemplate.objects.create(
            name="Admin OK Template",
            url="https://mcp.admin-ok.example.com/mcp",
            auth_type="api_key",
            is_active=True,
        )
        response = self.client.post(
            self._api_url("install_template/"),
            data={"template_id": str(template.id), "api_key": "k", "scope": "shared"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["scope"] == "shared"

    def test_non_owner_cannot_change_tool_approval_shared(self) -> None:
        from django.utils import timezone

        from posthog.models import User

        from products.mcp_store.backend.models import MCPServerInstallationTool

        other = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        shared = self._create_installation(user=other, scope="shared")
        tool = MCPServerInstallationTool.objects.create(
            installation=shared,
            tool_name="delete_everything",
            approval_state="needs_approval",
            last_seen_at=timezone.now(),
        )

        response = self.client.patch(
            self._api_url(f"{shared.id}/tools/{tool.tool_name}/"),
            data={"approval_state": "approved"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        tool.refresh_from_db()
        assert tool.approval_state == "needs_approval"

    def test_owner_can_change_tool_approval_shared(self) -> None:
        from django.utils import timezone

        from products.mcp_store.backend.models import MCPServerInstallationTool

        shared = self._create_installation(scope="shared")
        tool = MCPServerInstallationTool.objects.create(
            installation=shared,
            tool_name="safe_tool",
            approval_state="needs_approval",
            last_seen_at=timezone.now(),
        )

        response = self.client.patch(
            self._api_url(f"{shared.id}/tools/{tool.tool_name}/"),
            data={"approval_state": "approved"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        tool.refresh_from_db()
        assert tool.approval_state == "approved"

    def test_non_owner_cannot_hijack_shared_via_install_template(self) -> None:
        from posthog.models import User

        # Admin so the request clears the admin gate and exercises the owner guard.
        self._make_admin()
        other = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        template = MCPServerTemplate.objects.create(
            name="Shared Template",
            url="https://mcp.shared-template.example.com/mcp",
            auth_type="api_key",
            is_active=True,
        )
        shared = self._create_installation(
            user=other,
            scope="shared",
            url=template.url,
            template=template,
            sensitive_configuration={"api_key": "owner-key"},
        )

        response = self.client.post(
            self._api_url("install_template/"),
            data={"template_id": str(template.id), "api_key": "attacker-key", "scope": "shared"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        shared.refresh_from_db()
        assert shared.sensitive_configuration["api_key"] == "owner-key"

    @ALLOW_URL
    @patch("products.mcp_store.backend.presentation.views.discover_oauth_metadata")
    def test_non_owner_cannot_hijack_shared_via_install_custom_oauth(self, mock_discover, _allow) -> None:
        from posthog.models import User

        # Admin so the request clears the admin gate and exercises the owner guard.
        self._make_admin()
        other = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        shared = self._create_installation(
            user=other,
            scope="shared",
            auth_type="oauth",
            url="https://mcp.shared-oauth.example.com/mcp",
            sensitive_configuration={"dcr_client_id": "owner-client", "access_token": "owner-token"},
        )

        response = self.client.post(
            self._api_url("install_custom/"),
            data={
                "name": "Hijack",
                "url": shared.url,
                "auth_type": "oauth",
                "scope": "shared",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        # Guard must fire before any discovery/DCR work touches the row.
        mock_discover.assert_not_called()
        shared.refresh_from_db()
        assert shared.sensitive_configuration["dcr_client_id"] == "owner-client"
        assert shared.sensitive_configuration["access_token"] == "owner-token"

    @ALLOW_URL
    def test_install_custom_defaults_to_personal(self, _mock) -> None:
        response = self.client.post(
            self._api_url("install_custom/"),
            data={
                "name": "Personal Custom",
                "url": "https://mcp.personal-custom.example.com/mcp",
                "auth_type": "api_key",
                "api_key": "key123",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["scope"] == "personal"


class TestMCPScopeAdminGateWithAccessControlFeature(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    """Regression tests for the admin gate on shared-credential management.

    With the ACCESS_CONTROL feature available and a project that has no
    access-control rows configured, `effective_membership_level` reports
    every org member as project admin (open-project default). The share /
    unshare / shared-delete gate must not inherit that default: only org
    admins and explicitly-granted project admins pass.
    """

    def setUp(self):
        super().setUp()
        from posthog.constants import AvailableFeature

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

    def _api_url(self, suffix: str = "") -> str:
        base = f"/api/environments/{self.team.id}/mcp_server_installations/"
        return f"{base}{suffix}" if suffix else base

    def _create_installation(self, user=None, scope="personal") -> MCPServerInstallation:
        import uuid as _uuid

        return MCPServerInstallation.objects.create(
            team=self.team,
            user=user or self.user,
            display_name=f"Server-{_uuid.uuid4().hex[:6]}",
            url=f"https://mcp.test-{_uuid.uuid4().hex[:8]}.example.com/mcp",
            auth_type="api_key",
            is_enabled=True,
            scope=scope,
        )

    def _other_user(self):
        from posthog.models import User

        return User.objects.create_and_join(self.organization, "other@posthog.com", "password")

    def _make_org_admin(self) -> None:
        from posthog.models import OrganizationMembership

        membership = self.user.organization_memberships.get(organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

    def test_member_cannot_unshare_anothers_shared_on_open_project(self) -> None:
        shared = self._create_installation(user=self._other_user(), scope="shared")

        response = self.client.post(self._api_url(f"{shared.id}/unshare/"))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        shared.refresh_from_db()
        assert shared.scope == "shared"

    def test_member_cannot_delete_anothers_shared_on_open_project(self) -> None:
        shared = self._create_installation(user=self._other_user(), scope="shared")

        response = self.client.delete(self._api_url(f"{shared.id}/"))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert MCPServerInstallation.objects.filter(id=shared.id).exists()

    def test_member_cannot_share_own_personal_on_open_project(self) -> None:
        personal = self._create_installation(scope="personal")

        response = self.client.post(self._api_url(f"{personal.id}/share/"))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        personal.refresh_from_db()
        assert personal.scope == "personal"

    def test_org_admin_can_unshare_on_open_project(self) -> None:
        self._make_org_admin()
        shared = self._create_installation(user=self._other_user(), scope="shared")

        response = self.client.post(self._api_url(f"{shared.id}/unshare/"))

        assert response.status_code == status.HTTP_200_OK
        shared.refresh_from_db()
        assert shared.scope == "personal"

    def test_explicit_project_admin_can_unshare(self) -> None:
        from ee.models.rbac.access_control import AccessControl

        membership = self.user.organization_memberships.get(organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="admin",
            organization_member=membership,
        )
        shared = self._create_installation(user=self._other_user(), scope="shared")

        response = self.client.post(self._api_url(f"{shared.id}/unshare/"))

        assert response.status_code == status.HTTP_200_OK
        shared.refresh_from_db()
        assert shared.scope == "personal"

    def test_owner_can_still_unshare_own_shared_as_member(self) -> None:
        # The credential owner reclaims their own connection regardless of role.
        shared = self._create_installation(scope="shared")

        response = self.client.post(self._api_url(f"{shared.id}/unshare/"))

        assert response.status_code == status.HTTP_200_OK
        shared.refresh_from_db()
        assert shared.scope == "personal"
