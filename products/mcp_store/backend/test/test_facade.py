from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import User

from products.mcp_store.backend.facade.api import get_active_installations, get_installations_for_sandbox
from products.mcp_store.backend.facade.contracts import ActiveInstallationInfo
from products.mcp_store.backend.models import MCPServerInstallation, MCPServerTemplate


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
            ActiveInstallationInfo(
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

    def test_shared_always_returned(self) -> None:
        shared = self._create_installation(scope="shared", display_name="Shared Server")

        results = get_installations_for_sandbox(self.team.id)

        assert len(results) == 1
        assert results[0].id == str(shared.id)
        assert results[0].scope == "shared"

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
