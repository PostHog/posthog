from urllib.parse import urlparse

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import TestCase

import requests
from parameterized import parameterized

from products.mcp_store.backend.models import MCPServerInstallation, MCPServerTemplate
from products.mcp_store.backend.oauth import (
    TIMEOUT,
    OAuthTokenExchangeError,
    SSRFBlockedError,
    TokenRefreshError,
    _resolve_issuer,
    discover_oauth_metadata,
    exchange_oauth_token,
    refresh_oauth_token,
    register_dcr_client,
    resolve_installation_oauth_context,
)


class TestResolveIssuer(TestCase):
    @parameterized.expand(
        [
            (
                "matching_issuer_returns_metadata_unchanged",
                {"issuer": "https://auth.example.com", "authorization_endpoint": "/authorize"},
                "https://auth.example.com",
                {"issuer": "https://auth.example.com", "authorization_endpoint": "/authorize"},
            ),
            (
                "trailing_slash_treated_as_matching",
                {"issuer": "https://auth.example.com/", "authorization_endpoint": "/authorize"},
                "https://auth.example.com",
                {"issuer": "https://auth.example.com/", "authorization_endpoint": "/authorize"},
            ),
            (
                "no_issuer_defaults_to_expected",
                {"authorization_endpoint": "/authorize"},
                "https://auth.example.com",
                {"issuer": "https://auth.example.com", "authorization_endpoint": "/authorize"},
            ),
            (
                "empty_issuer_not_overwritten",
                {"issuer": "", "authorization_endpoint": "/authorize"},
                "https://auth.example.com",
                {"issuer": "", "authorization_endpoint": "/authorize"},
            ),
        ]
    )
    def test_no_cross_validation_needed(self, _name, metadata, expected_issuer, expected_result):
        result = _resolve_issuer(metadata, expected_issuer)
        self.assertEqual(result, expected_result)

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.get")
    def test_mismatched_issuer_triggers_cross_validation(self, mock_get, _allow):
        cross_validated = {
            "issuer": "https://real-auth.example.com",
            "authorization_endpoint": "https://real-auth.example.com/authorize",
            "token_endpoint": "https://real-auth.example.com/token",
        }
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = cross_validated
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        metadata = {
            "issuer": "https://real-auth.example.com",
            "authorization_endpoint": "https://evil.com/authorize",
            "token_endpoint": "https://evil.com/token",
        }
        result = _resolve_issuer(metadata, "https://evil.com")

        self.assertEqual(result, cross_validated)
        mock_get.assert_called_once()
        self.assertIn("real-auth.example.com", mock_get.call_args.args[0])

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.get")
    def test_cross_validation_mismatch_raises(self, mock_get, _allow):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "issuer": "https://someone-else.com",
            "authorization_endpoint": "https://someone-else.com/authorize",
            "token_endpoint": "https://someone-else.com/token",
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        metadata = {
            "issuer": "https://claimed-auth.example.com",
            "authorization_endpoint": "https://origin.com/authorize",
            "token_endpoint": "https://origin.com/token",
        }
        with self.assertRaises(ValueError, msg="Issuer mismatch"):
            _resolve_issuer(metadata, "https://origin.com")

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.get")
    def test_cross_validation_fetch_fails(self, mock_get, _allow):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp

        metadata = {
            "issuer": "https://unreachable-auth.example.com",
            "authorization_endpoint": "https://origin.com/authorize",
            "token_endpoint": "https://origin.com/token",
        }
        with self.assertRaises(requests.HTTPError):
            _resolve_issuer(metadata, "https://origin.com")


class TestRefreshOauthToken(TestCase):
    @parameterized.expand(
        [
            (
                "known_provider_with_secret",
                {"client_secret": "my-secret"},
                {"client_secret": "my-secret"},
            ),
            (
                "dcr_without_secret",
                {"client_secret": None},
                {},
            ),
        ]
    )
    def test_client_secret_inclusion(self, _name, kwargs, expected_extra_data):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "new-token", "refresh_token": "new-refresh"}
        mock_resp.raise_for_status = MagicMock()

        with patch("products.mcp_store.backend.oauth.requests.post", return_value=mock_resp) as mock_post:
            result = refresh_oauth_token(
                token_url="https://example.com/token",
                refresh_token="old-refresh",
                client_id="my-client",
                **kwargs,
            )

        call_data = mock_post.call_args[1]["data"]
        self.assertEqual(call_data["grant_type"], "refresh_token")
        self.assertEqual(call_data["refresh_token"], "old-refresh")
        self.assertEqual(call_data["client_id"], "my-client")
        if expected_extra_data:
            self.assertEqual(call_data["client_secret"], expected_extra_data["client_secret"])
        else:
            self.assertNotIn("client_secret", call_data)
        self.assertEqual(result["access_token"], "new-token")

    def test_http_error_raises_token_refresh_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("401 Unauthorized", response=mock_resp)

        with patch("products.mcp_store.backend.oauth.requests.post", return_value=mock_resp):
            with self.assertRaises(TokenRefreshError) as ctx:
                refresh_oauth_token(
                    token_url="https://example.com/token",
                    refresh_token="bad-refresh",
                    client_id="my-client",
                )
            self.assertIn("Token refresh request failed", str(ctx.exception))

    def test_missing_access_token_raises_token_refresh_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"error": "invalid_grant"}
        mock_resp.raise_for_status = MagicMock()

        with patch("products.mcp_store.backend.oauth.requests.post", return_value=mock_resp):
            with self.assertRaises(TokenRefreshError) as ctx:
                refresh_oauth_token(
                    token_url="https://example.com/token",
                    refresh_token="expired-refresh",
                    client_id="my-client",
                )
            self.assertIn("missing access_token", str(ctx.exception))

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(False, "Private IP address not allowed"))
    def test_ssrf_blocked_token_url_raises_token_refresh_error(self, _mock):
        with self.assertRaises(TokenRefreshError) as ctx:
            refresh_oauth_token(
                token_url="http://169.254.169.254/latest/meta-data/",
                refresh_token="tok",
                client_id="cid",
            )
        self.assertIn("SSRF protection", str(ctx.exception))


class TestIssuerValidation(TestCase):
    def _make_response(self, *, ok=True, status_code=200, json_data=None):
        resp = MagicMock()
        resp.ok = ok
        resp.status_code = status_code
        resp.json.return_value = json_data or {}
        resp.raise_for_status = MagicMock()
        if status_code >= 400:
            resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
        return resp

    def _origin(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _auth_metadata_url(self, auth_server_url: str) -> str:
        parsed = urlparse(auth_server_url)
        if parsed.path and parsed.path != "/":
            return f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-authorization-server{parsed.path}"
        return f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-authorization-server"

    @parameterized.expand(
        [
            (
                "matching_issuer_accepted",
                {
                    "issuer": "https://evil.com",
                    "authorization_endpoint": "https://evil.com/authorize",
                    "token_endpoint": "https://evil.com/token",
                },
                "https://evil.com/mcp",
                False,
                None,
            ),
            (
                "trailing_slash_accepted",
                {
                    "issuer": "https://example.com/",
                    "authorization_endpoint": "https://example.com/authorize",
                    "token_endpoint": "https://example.com/token",
                },
                "https://example.com/mcp",
                False,
                None,
            ),
            (
                "no_issuer_defaults_to_origin",
                {
                    "authorization_endpoint": "https://example.com/authorize",
                    "token_endpoint": "https://example.com/token",
                },
                "https://example.com/mcp",
                False,
                None,
            ),
            (
                "cross_validation_succeeds",
                {
                    "issuer": "https://cf.mcp.atlassian.com",
                    "authorization_endpoint": "https://cf.mcp.atlassian.com/v1/authorize",
                    "token_endpoint": "https://cf.mcp.atlassian.com/v1/token",
                },
                "https://mcp.atlassian.com/v1/mcp",
                False,
                {
                    "issuer": "https://cf.mcp.atlassian.com",
                    "authorization_endpoint": "https://cf.mcp.atlassian.com/v1/authorize",
                    "token_endpoint": "https://cf.mcp.atlassian.com/v1/token",
                },
            ),
            (
                "cross_validation_fails_issuer_mismatch",
                {
                    "issuer": "https://accounts.notion.com",
                    "authorization_endpoint": "https://evil.com/authorize",
                    "token_endpoint": "https://evil.com/token",
                },
                "https://evil.com/mcp",
                True,
                {
                    "issuer": "https://real-notion-auth.com",
                    "authorization_endpoint": "https://real-notion-auth.com/authorize",
                    "token_endpoint": "https://real-notion-auth.com/token",
                },
            ),
            (
                "cross_validation_fails_declared_issuer_404",
                {
                    "issuer": "https://nonexistent.example.com",
                    "authorization_endpoint": "https://nonexistent.example.com/authorize",
                    "token_endpoint": "https://nonexistent.example.com/token",
                },
                "https://evil.com/mcp",
                True,
                None,
            ),
        ]
    )
    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.get")
    def test_step2_fallback_issuer_validation(
        self, _name, auth_metadata, server_url, should_raise, cross_val_metadata, mock_get, _allow
    ):
        not_found = self._make_response(ok=False, status_code=404)
        auth_resp = self._make_response(json_data=auth_metadata)
        expected_origin = self._origin(server_url)
        expected_path = urlparse(server_url).path.rstrip("/")

        declared_issuer = auth_metadata.get("issuer", "").rstrip("/")
        needs_cross_validation = bool(declared_issuer and declared_issuer != expected_origin.rstrip("/"))

        responses: list = [not_found, not_found, auth_resp]
        expected_urls = [
            f"{expected_origin}/.well-known/oauth-protected-resource{expected_path}",
            f"{expected_origin}/.well-known/oauth-protected-resource",
            self._auth_metadata_url(expected_origin),
        ]

        if needs_cross_validation:
            if cross_val_metadata is not None:
                responses.append(self._make_response(json_data=cross_val_metadata))
            else:
                responses.append(self._make_response(ok=False, status_code=404))
            expected_urls.append(self._auth_metadata_url(declared_issuer))

        mock_get.side_effect = responses

        if should_raise:
            with self.assertRaises(Exception):
                discover_oauth_metadata(server_url)
        else:
            metadata = discover_oauth_metadata(server_url)
            assert metadata["issuer"] == auth_metadata.get("issuer", expected_origin)

        assert mock_get.call_count == len(expected_urls)
        for index, expected_url in enumerate(expected_urls):
            assert mock_get.call_args_list[index].args[0] == expected_url
            assert mock_get.call_args_list[index].kwargs["timeout"] == TIMEOUT

    @parameterized.expand(
        [
            (
                "matching_issuer_accepted",
                "https://auth.example.com",
                {
                    "issuer": "https://auth.example.com",
                    "authorization_endpoint": "https://auth.example.com/authorize",
                    "token_endpoint": "https://auth.example.com/token",
                },
                False,
                None,
            ),
            (
                "cross_origin_mcp_with_legitimate_auth_server",
                "https://accounts.notion.com",
                {
                    "issuer": "https://accounts.notion.com",
                    "authorization_endpoint": "https://accounts.notion.com/authorize",
                    "token_endpoint": "https://accounts.notion.com/token",
                },
                False,
                None,
            ),
            (
                "auth_server_with_path_accepted",
                "https://auth.example.com/oauth2/default",
                {
                    "issuer": "https://auth.example.com/oauth2/default",
                    "authorization_endpoint": "https://auth.example.com/oauth2/default/authorize",
                    "token_endpoint": "https://auth.example.com/oauth2/default/token",
                },
                False,
                None,
            ),
            (
                "cross_validation_succeeds",
                "https://auth.example.com",
                {
                    "issuer": "https://cf.auth.example.com",
                    "authorization_endpoint": "https://cf.auth.example.com/authorize",
                    "token_endpoint": "https://cf.auth.example.com/token",
                },
                False,
                {
                    "issuer": "https://cf.auth.example.com",
                    "authorization_endpoint": "https://cf.auth.example.com/authorize",
                    "token_endpoint": "https://cf.auth.example.com/token",
                },
            ),
            (
                "cross_validation_fails_issuer_mismatch",
                "https://auth.example.com",
                {
                    "issuer": "https://evil.com",
                    "authorization_endpoint": "https://evil.com/authorize",
                    "token_endpoint": "https://evil.com/token",
                },
                True,
                {
                    "issuer": "https://real-evil.com",
                    "authorization_endpoint": "https://real-evil.com/authorize",
                    "token_endpoint": "https://real-evil.com/token",
                },
            ),
            (
                "cross_validation_fails_declared_issuer_404",
                "https://auth.example.com",
                {
                    "issuer": "https://nonexistent.example.com",
                    "authorization_endpoint": "https://nonexistent.example.com/authorize",
                    "token_endpoint": "https://nonexistent.example.com/token",
                },
                True,
                None,
            ),
        ]
    )
    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.get")
    def test_step1_protected_resource_issuer_validation(
        self, _name, auth_server_url, auth_metadata, should_raise, cross_val_metadata, mock_get, _allow
    ):
        resource_resp = self._make_response(json_data={"authorization_servers": [auth_server_url]})
        auth_resp = self._make_response(json_data=auth_metadata)
        mcp_url = "https://mcp.example.com/mcp"

        declared_issuer = auth_metadata.get("issuer", "").rstrip("/")
        needs_cross_validation = bool(declared_issuer and declared_issuer != auth_server_url.rstrip("/"))

        responses: list = [resource_resp, auth_resp]
        expected_urls = [
            "https://mcp.example.com/.well-known/oauth-protected-resource/mcp",
            self._auth_metadata_url(auth_server_url),
        ]

        if needs_cross_validation:
            if cross_val_metadata is not None:
                responses.append(self._make_response(json_data=cross_val_metadata))
            else:
                responses.append(self._make_response(ok=False, status_code=404))
            expected_urls.append(self._auth_metadata_url(declared_issuer))

        mock_get.side_effect = responses

        if should_raise:
            with self.assertRaises(Exception):
                discover_oauth_metadata(mcp_url)
        else:
            metadata = discover_oauth_metadata(mcp_url)
            assert metadata["issuer"] == auth_metadata.get("issuer", auth_server_url)

        assert mock_get.call_count == len(expected_urls)
        for index, expected_url in enumerate(expected_urls):
            assert mock_get.call_args_list[index].args[0] == expected_url
            assert mock_get.call_args_list[index].kwargs["timeout"] == TIMEOUT


class TestSSRFProtection(TestCase):
    @parameterized.expand(
        [
            (
                "discover_blocks_internal_server_url",
                "discover_oauth_metadata",
                {"server_url": "http://169.254.169.254/mcp"},
            ),
            (
                "register_dcr_blocks_internal_registration_endpoint",
                "register_dcr_client",
                {
                    "metadata": {"registration_endpoint": "http://10.0.0.1/register"},
                    "redirect_uri": "https://app.posthog.com/callback",
                },
            ),
        ]
    )
    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(False, "Disallowed target IP"))
    def test_ssrf_blocked(self, _name, func_name, kwargs, _mock):
        func = {
            "discover_oauth_metadata": discover_oauth_metadata,
            "register_dcr_client": register_dcr_client,
        }[func_name]
        with self.assertRaises(SSRFBlockedError):
            func(**kwargs)  # type: ignore[operator]


class TestResolveInstallationOauthContext(BaseTest):
    def test_template_backed_install_returns_template_creds(self):
        template = MCPServerTemplate.objects.create(
            name="Template",
            url="https://mcp.template.example.com/mcp",
            auth_type="oauth",
            oauth_metadata={"token_endpoint": "https://auth.template.example.com/token"},
            oauth_credentials={"client_id": "template-client", "client_secret": "template-secret"},
            created_by=self.user,
        )
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            template=template,
            url=template.url,
            auth_type="oauth",
            # Installation sensitive_configuration does NOT carry a dcr_client_secret
            # for template installs — creds live on the template.
            sensitive_configuration={"access_token": "tok"},
        )

        metadata, client_id, client_secret = resolve_installation_oauth_context(installation)

        assert metadata["token_endpoint"] == "https://auth.template.example.com/token"
        assert client_id == "template-client"
        assert client_secret == "template-secret"

    def test_dcr_template_backed_install_returns_per_installation_metadata_and_creds(self):
        # DCR templates carry no shared client_id AND no trusted metadata —
        # both were discovered + minted at install time and cached on the
        # installation (never written back to the template). The resolver
        # must read both from the installation, matching the custom-install
        # path.
        template = MCPServerTemplate.objects.create(
            name="DCR Template",
            url="https://mcp.dcr-template.example.com/mcp",
            auth_type="oauth",
            oauth_metadata={},
            oauth_credentials={},
            created_by=self.user,
        )
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            template=template,
            url=template.url,
            auth_type="oauth",
            oauth_metadata={"token_endpoint": "https://auth.dcr-template.example.com/token"},
            sensitive_configuration={
                "dcr_client_id": "minted-for-user",
                "access_token": "tok",
            },
        )

        metadata, client_id, client_secret = resolve_installation_oauth_context(installation)

        assert metadata["token_endpoint"] == "https://auth.dcr-template.example.com/token"
        assert client_id == "minted-for-user"
        assert client_secret is None

    def test_custom_install_returns_per_installation_dcr_creds(self):
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            url="https://mcp.custom.example.com/mcp",
            auth_type="oauth",
            oauth_metadata={"token_endpoint": "https://auth.custom.example.com/token"},
            sensitive_configuration={
                "dcr_client_id": "per-user-client",
                "dcr_client_secret": "per-user-secret",
            },
        )

        metadata, client_id, client_secret = resolve_installation_oauth_context(installation)

        assert metadata["token_endpoint"] == "https://auth.custom.example.com/token"
        assert client_id == "per-user-client"
        assert client_secret == "per-user-secret"

    def test_custom_install_without_secret_returns_none(self):
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            url="https://mcp.custom.example.com/mcp",
            auth_type="oauth",
            oauth_metadata={"token_endpoint": "https://auth.custom.example.com/token"},
            sensitive_configuration={"dcr_client_id": "public-client"},
        )

        _metadata, _client_id, client_secret = resolve_installation_oauth_context(installation)

        assert client_secret is None


class TestExchangeOauthToken(BaseTest):
    def _make_installation(self, *, sensitive_configuration: dict) -> MCPServerInstallation:
        return MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            url="https://mcp.custom.example.com/mcp",
            auth_type="oauth",
            oauth_metadata={"token_endpoint": "https://auth.custom.example.com/token"},
            sensitive_configuration=sensitive_configuration,
        )

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_confidential_custom_install_sends_client_secret(self, mock_post, _allow):
        """dcr_client_secret round-trips through resolve_installation_oauth_context into the token exchange body."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "abc", "refresh_token": "def"}
        mock_post.return_value = mock_resp

        installation = self._make_installation(
            sensitive_configuration={
                "dcr_client_id": "confidential-client",
                "dcr_client_secret": "confidential-secret",
            },
        )

        result = exchange_oauth_token(
            installation=installation,
            code="auth-code",
            pkce_verifier="pkce-verifier",
            redirect_uri="https://app.posthog.com/callback",
            is_https=lambda url: url.startswith("https://"),
        )

        assert result["access_token"] == "abc"
        sent_form = mock_post.call_args[1]["data"]
        assert sent_form["client_id"] == "confidential-client"
        assert sent_form["client_secret"] == "confidential-secret"
        assert sent_form["grant_type"] == "authorization_code"
        assert sent_form["code_verifier"] == "pkce-verifier"

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_public_custom_install_omits_client_secret(self, mock_post, _allow):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "abc"}
        mock_post.return_value = mock_resp

        installation = self._make_installation(
            sensitive_configuration={"dcr_client_id": "public-client"},
        )

        exchange_oauth_token(
            installation=installation,
            code="auth-code",
            pkce_verifier="pkce-verifier",
            redirect_uri="https://app.posthog.com/callback",
            is_https=lambda url: url.startswith("https://"),
        )

        sent_form = mock_post.call_args[1]["data"]
        assert "client_secret" not in sent_form

    def test_missing_pkce_verifier_raises(self):
        installation = self._make_installation(
            sensitive_configuration={"dcr_client_id": "public-client"},
        )

        with self.assertRaises(OAuthTokenExchangeError):
            exchange_oauth_token(
                installation=installation,
                code="auth-code",
                pkce_verifier="",
                redirect_uri="https://app.posthog.com/callback",
                is_https=lambda url: url.startswith("https://"),
            )
