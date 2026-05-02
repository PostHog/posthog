import hashlib
from urllib.parse import parse_qs, urlparse

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from products.mcp_store.backend.models import MCPOAuthState, MCPServerInstallation, MCPServerTemplate
from products.mcp_store.backend.presentation.views import _is_valid_posthog_code_callback_url

ALLOW_URL = patch("products.mcp_store.backend.presentation.views.is_url_allowed", return_value=(True, None))


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
        expected_keys = {"id", "name", "url", "docs_url", "description", "auth_type", "icon_key", "category"}
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

    def test_unauthenticated_access(self):
        client = APIClient()
        response = client.get(f"/api/environments/{self.team.id}/mcp_servers/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


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
        assert results[0]["icon_key"] == ""

    def test_list_installation_icon_key_from_template(self):
        # Pass a non-normalized icon_key to confirm the model's save() normalizes it
        # and the value flows through the serializer unchanged.
        template = MCPServerTemplate.objects.create(
            name="PostHog MCP",
            url="https://mcp.notion.example/mcp",
            description="d",
            auth_type="api_key",
            is_active=True,
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

    def test_callback_rejects_state_for_anonymous_consumer(self):
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

    def test_callback_rejects_state_for_different_authenticated_user(self):
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
            {"state": state_token, "code": "victim-auth-code"},
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
    @patch("products.mcp_store.backend.presentation.views.register_dcr_client", return_value="dcr-client-id")
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
        mock_dcr.return_value = "per-user-dcr-client"

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
        # EncryptedJSONField stringifies leaf values on round-trip; accept either bool or str.
        assert installation.sensitive_configuration["dcr_is_user_provided"] in (False, "False")

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
        # EncryptedJSONField stringifies leaf values on round-trip; accept either bool or str.
        assert sensitive["dcr_is_user_provided"] in (True, "True")

        params = parse_qs(urlparse(response.json()["redirect_url"]).query)
        assert params["client_id"][0] == "user-supplied-client-id"

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
        mock_dcr.return_value = "dcr-minted-client"

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
        assert sensitive["dcr_is_user_provided"] in (False, "False")

    @ALLOW_URL
    @patch("products.mcp_store.backend.presentation.views.register_dcr_client", return_value="new-dcr-client")
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
        return_value="minted-per-user-client",
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
