from urllib.parse import urlparse

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

import requests
from parameterized import parameterized

from products.mcp_store.backend.models import MCPServerInstallation, MCPServerTemplate
from products.mcp_store.backend.oauth import (
    TIMEOUT,
    OAuthTokenExchangeError,
    SSRFBlockedError,
    TokenRefreshError,
    _resolve_issuer,
    _validate_endpoints_bound_to_issuer,
    discover_oauth_metadata,
    exchange_oauth_token,
    oauth_resource,
    refresh_oauth_token,
    register_dcr_client,
    requested_oauth_grant_types,
    requested_oauth_scopes,
    resolve_installation_oauth_context,
    select_token_endpoint_auth_method,
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


class TestRefreshOauthToken(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "known_provider_with_secret",
                {"client_secret": "my-secret"},
                ("my-client", "my-secret"),
            ),
            (
                "dcr_without_secret",
                {"client_secret": None},
                None,
            ),
        ]
    )
    def test_default_token_auth_method(self, _name, kwargs, expected_auth):
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

        call_kwargs = mock_post.call_args.kwargs
        call_data = call_kwargs["data"]
        self.assertEqual(call_data["grant_type"], "refresh_token")
        self.assertEqual(call_data["refresh_token"], "old-refresh")
        if expected_auth:
            self.assertNotIn("client_id", call_data)
            self.assertNotIn("client_secret", call_data)
        else:
            self.assertEqual(call_data["client_id"], "my-client")
            self.assertNotIn("client_secret", call_data)
        self.assertEqual(call_kwargs["auth"], expected_auth)
        self.assertEqual(result["access_token"], "new-token")

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_refresh_sends_resource_and_disables_redirects(self, mock_post, _allow):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "new-token"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        refresh_oauth_token(
            token_url="https://example.com/token",
            refresh_token="old-refresh",
            client_id="my-client",
            resource="https://mcp.example.com/",
        )

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["allow_redirects"] is False
        assert call_kwargs["data"]["resource"] == "https://mcp.example.com/"

    def test_http_error_raises_token_refresh_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
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


class TestIssuerValidation(SimpleTestCase):
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

    def _auth_metadata_chain(self, auth_server_url: str) -> list[str]:
        parsed = urlparse(auth_server_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if parsed.path and parsed.path != "/":
            path = parsed.path.rstrip("/")
            return [
                f"{origin}/.well-known/oauth-authorization-server{path}",
                f"{origin}/.well-known/openid-configuration{path}",
                f"{origin}{path}/.well-known/openid-configuration",
            ]
        return [
            f"{origin}/.well-known/oauth-authorization-server",
            f"{origin}/.well-known/openid-configuration",
        ]

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
                expected_urls.append(self._auth_metadata_url(declared_issuer))
            else:
                chain = self._auth_metadata_chain(declared_issuer)
                responses.extend(self._make_response(ok=False, status_code=404) for _ in chain)
                expected_urls.extend(chain)

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
                expected_urls.append(self._auth_metadata_url(declared_issuer))
            else:
                chain = self._auth_metadata_chain(declared_issuer)
                responses.extend(self._make_response(ok=False, status_code=404) for _ in chain)
                expected_urls.extend(chain)

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

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.get")
    def test_step1_preserves_same_origin_resource(self, mock_get, _allow):
        auth_server_url = "https://auth.example.com"
        resource_resp = self._make_response(
            json_data={
                "resource": "https://mcp.example.com/mcp",
                "authorization_servers": [auth_server_url],
            }
        )
        auth_resp = self._make_response(
            json_data={
                "issuer": auth_server_url,
                "authorization_endpoint": f"{auth_server_url}/authorize",
                "token_endpoint": f"{auth_server_url}/token",
            }
        )
        mock_get.side_effect = [resource_resp, auth_resp]

        metadata = discover_oauth_metadata("https://mcp.example.com/mcp")

        assert metadata["resource"] == "https://mcp.example.com/mcp"
        assert mock_get.call_count == 2

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.get")
    def test_step1_rejects_resource_on_unrelated_origin(self, mock_get, _allow):
        resource_resp = self._make_response(
            json_data={
                "resource": "https://api.legit.com",
                "authorization_servers": ["https://auth.legit.com"],
            }
        )
        mock_get.return_value = resource_resp

        with self.assertRaisesMessage(ValueError, "not bound to MCP server"):
            discover_oauth_metadata("https://mcp.attacker.com/mcp")

        assert mock_get.call_count == 1

    @parameterized.expand(
        [
            (
                "token_endpoint_redirected_to_attacker",
                {
                    "issuer": "https://auth.legit.com",
                    "authorization_endpoint": "https://auth.legit.com/authorize",
                    "token_endpoint": "https://attacker.com/token",
                    "registration_endpoint": "https://auth.legit.com/register",
                },
            ),
            (
                "registration_endpoint_redirected_to_attacker",
                {
                    "issuer": "https://auth.legit.com",
                    "authorization_endpoint": "https://auth.legit.com/authorize",
                    "token_endpoint": "https://auth.legit.com/token",
                    "registration_endpoint": "https://attacker.com/register",
                },
            ),
        ]
    )
    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.get")
    def test_rejects_metadata_with_endpoints_off_issuer_origin(self, _name, auth_metadata, mock_get, _allow):
        """A malicious MCP server cannot mix a legitimate issuer with an attacker-controlled endpoint.

        Otherwise, after the user authorizes against the real provider, the
        token exchange would ship the code, PKCE verifier, and any DCR-minted
        client_secret to the attacker.
        """
        resource_resp = self._make_response(json_data={"authorization_servers": ["https://auth.legit.com"]})
        auth_resp = self._make_response(json_data=auth_metadata)
        mock_get.side_effect = [resource_resp, auth_resp]

        with self.assertRaises(ValueError):
            discover_oauth_metadata("https://mcp.legit.com/mcp")


class TestAuthServerMetadataDiscoveryChain(TestCase):
    """Verifies the MCP-spec-mandated discovery chain for authorization server metadata.

    Spec: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
    §2.3 "Authorization Server Metadata Discovery".
    """

    def _make_response(self, *, ok=True, status_code=200, json_data=None):
        resp = MagicMock()
        resp.ok = ok
        resp.status_code = status_code
        resp.json.return_value = json_data or {}
        resp.raise_for_status = MagicMock()
        if status_code >= 400:
            resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
        return resp

    def _valid_metadata(self, issuer: str) -> dict:
        return {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/authorize",
            "token_endpoint": f"{issuer}/token",
        }

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.get")
    def test_variant_1_success_makes_no_fallback_calls(self, mock_get, _allow):
        """Regression guard: when variant 1 succeeds, the loop stops — no fallback URLs are tried."""
        mcp_url = "https://mcp.example.com"
        auth_server_url = "https://mcp.example.com/oauth"
        resource_resp = self._make_response(json_data={"authorization_servers": [auth_server_url]})
        auth_resp = self._make_response(json_data=self._valid_metadata(auth_server_url))

        mock_get.side_effect = [resource_resp, auth_resp]

        metadata = discover_oauth_metadata(mcp_url)
        assert metadata["issuer"] == auth_server_url

        expected_urls = [
            "https://mcp.example.com/.well-known/oauth-protected-resource",
            "https://mcp.example.com/.well-known/oauth-authorization-server/oauth",
        ]
        assert mock_get.call_count == len(expected_urls)
        for index, expected_url in enumerate(expected_urls):
            assert mock_get.call_args_list[index].args[0] == expected_url

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.get")
    def test_auth_server_with_path_falls_back_to_oidc_path_insertion(self, mock_get, _allow):
        """Variant 1 404s, variant 2 (OIDC path insertion) succeeds."""
        mcp_url = "https://mcp.example.com"
        auth_server_url = "https://mcp.example.com/oauth"
        resource_resp = self._make_response(json_data={"authorization_servers": [auth_server_url]})
        not_found = self._make_response(ok=False, status_code=404)
        auth_resp = self._make_response(json_data=self._valid_metadata(auth_server_url))

        mock_get.side_effect = [resource_resp, not_found, auth_resp]

        metadata = discover_oauth_metadata(mcp_url)
        assert metadata["issuer"] == auth_server_url

        expected_urls = [
            "https://mcp.example.com/.well-known/oauth-protected-resource",
            "https://mcp.example.com/.well-known/oauth-authorization-server/oauth",
            "https://mcp.example.com/.well-known/openid-configuration/oauth",
        ]
        assert mock_get.call_count == len(expected_urls)
        for index, expected_url in enumerate(expected_urls):
            assert mock_get.call_args_list[index].args[0] == expected_url

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.get")
    def test_auth_server_with_path_falls_back_to_oidc_path_append(self, mock_get, _allow):
        """Variants 1 and 2 404, variant 3 (OIDC path append) succeeds — the BuildBetter case."""
        mcp_url = "https://mcp.example.com"
        auth_server_url = "https://mcp.example.com/oauth"
        resource_resp = self._make_response(json_data={"authorization_servers": [auth_server_url]})
        not_found = self._make_response(ok=False, status_code=404)
        auth_resp = self._make_response(json_data=self._valid_metadata(auth_server_url))

        mock_get.side_effect = [resource_resp, not_found, not_found, auth_resp]

        metadata = discover_oauth_metadata(mcp_url)
        assert metadata["issuer"] == auth_server_url

        expected_urls = [
            "https://mcp.example.com/.well-known/oauth-protected-resource",
            "https://mcp.example.com/.well-known/oauth-authorization-server/oauth",
            "https://mcp.example.com/.well-known/openid-configuration/oauth",
            "https://mcp.example.com/oauth/.well-known/openid-configuration",
        ]
        assert mock_get.call_count == len(expected_urls)
        for index, expected_url in enumerate(expected_urls):
            assert mock_get.call_args_list[index].args[0] == expected_url

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.get")
    def test_auth_server_without_path_falls_back_to_oidc(self, mock_get, _allow):
        """Root auth-server URL: oauth-authorization-server 404, openid-configuration 200."""
        mcp_url = "https://mcp.example.com"
        auth_server_url = "https://auth.example.com"
        resource_resp = self._make_response(json_data={"authorization_servers": [auth_server_url]})
        not_found = self._make_response(ok=False, status_code=404)
        auth_resp = self._make_response(json_data=self._valid_metadata(auth_server_url))

        mock_get.side_effect = [resource_resp, not_found, auth_resp]

        metadata = discover_oauth_metadata(mcp_url)
        assert metadata["issuer"] == auth_server_url

        expected_urls = [
            "https://mcp.example.com/.well-known/oauth-protected-resource",
            "https://auth.example.com/.well-known/oauth-authorization-server",
            "https://auth.example.com/.well-known/openid-configuration",
        ]
        assert mock_get.call_count == len(expected_urls)
        for index, expected_url in enumerate(expected_urls):
            assert mock_get.call_args_list[index].args[0] == expected_url

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.get")
    def test_all_discovery_candidates_fail_raises(self, mock_get, _allow):
        """When every spec-mandated candidate returns 404, discovery raises and the view layer surfaces the 400."""
        mcp_url = "https://mcp.example.com"
        auth_server_url = "https://mcp.example.com/oauth"
        resource_resp = self._make_response(json_data={"authorization_servers": [auth_server_url]})
        not_found = self._make_response(ok=False, status_code=404)

        mock_get.side_effect = [resource_resp, not_found, not_found, not_found]

        with self.assertRaises(requests.HTTPError):
            discover_oauth_metadata(mcp_url)

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.get")
    def test_variant_1_malformed_metadata_does_not_fall_back(self, mock_get, _allow):
        """A 200 with malformed metadata is a real misconfiguration — surface it instead of probing fallbacks."""
        mcp_url = "https://mcp.example.com"
        auth_server_url = "https://mcp.example.com/oauth"
        resource_resp = self._make_response(json_data={"authorization_servers": [auth_server_url]})
        malformed = self._make_response(json_data={"issuer": auth_server_url})

        mock_get.side_effect = [resource_resp, malformed]

        with self.assertRaises(ValueError):
            discover_oauth_metadata(mcp_url)

        assert mock_get.call_count == 2

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.get")
    def test_variant_1_server_error_does_not_fall_back(self, mock_get, _allow):
        """A 500 is a transient failure, not 'endpoint not implemented' — surface it without retrying variants."""
        mcp_url = "https://mcp.example.com"
        auth_server_url = "https://mcp.example.com/oauth"
        resource_resp = self._make_response(json_data={"authorization_servers": [auth_server_url]})
        server_error = self._make_response(ok=False, status_code=500)

        mock_get.side_effect = [resource_resp, server_error]

        with self.assertRaises(requests.HTTPError):
            discover_oauth_metadata(mcp_url)

        assert mock_get.call_count == 2


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


class TestValidateEndpointsBoundToIssuer(TestCase):
    @parameterized.expand(
        [
            (
                "all_endpoints_match_issuer_origin",
                {
                    "issuer": "https://auth.example.com",
                    "authorization_endpoint": "https://auth.example.com/authorize",
                    "token_endpoint": "https://auth.example.com/token",
                    "registration_endpoint": "https://auth.example.com/register",
                },
            ),
            (
                "missing_registration_endpoint_is_ok",
                {
                    "issuer": "https://auth.example.com",
                    "authorization_endpoint": "https://auth.example.com/authorize",
                    "token_endpoint": "https://auth.example.com/token",
                },
            ),
            (
                "trailing_slash_on_issuer_tolerated",
                {
                    "issuer": "https://auth.example.com/",
                    "authorization_endpoint": "https://auth.example.com/authorize",
                    "token_endpoint": "https://auth.example.com/token",
                },
            ),
            (
                "sibling_subdomain_endpoints_accepted",
                {
                    "issuer": "https://auth.example.com",
                    "authorization_endpoint": "https://auth.example.com/authorize",
                    "token_endpoint": "https://token.example.com/token",
                },
            ),
            (
                "buildbetter_shape_endpoints_on_dedicated_auth_subdomain",
                {
                    "issuer": "https://mcp.buildbetter.app/oauth",
                    "authorization_endpoint": "https://auth.buildbetter.app/realms/buildbetter/protocol/openid-connect/auth",
                    "token_endpoint": "https://auth.buildbetter.app/realms/buildbetter/protocol/openid-connect/token",
                    "registration_endpoint": "https://mcp.buildbetter.app/register",
                },
            ),
            (
                "non_standard_port_in_issuer_does_not_break_registrable_domain_extraction",
                {
                    "issuer": "https://auth.example.com:8443",
                    "authorization_endpoint": "https://auth.example.com:8443/authorize",
                    "token_endpoint": "https://auth.example.com:8443/token",
                },
            ),
        ]
    )
    def test_accepts_aligned_metadata(self, _name, metadata):
        _validate_endpoints_bound_to_issuer(metadata)

    @parameterized.expand(
        [
            (
                "token_endpoint_on_attacker_origin",
                {
                    "issuer": "https://auth.example.com",
                    "authorization_endpoint": "https://auth.example.com/authorize",
                    "token_endpoint": "https://attacker.com/token",
                },
                "token_endpoint",
            ),
            (
                "authorization_endpoint_on_attacker_origin",
                {
                    "issuer": "https://auth.example.com",
                    "authorization_endpoint": "https://attacker.com/authorize",
                    "token_endpoint": "https://auth.example.com/token",
                },
                "authorization_endpoint",
            ),
            (
                "registration_endpoint_on_attacker_origin",
                {
                    "issuer": "https://auth.example.com",
                    "authorization_endpoint": "https://auth.example.com/authorize",
                    "token_endpoint": "https://auth.example.com/token",
                    "registration_endpoint": "https://attacker.com/register",
                },
                "registration_endpoint",
            ),
            (
                "scheme_downgrade_to_http",
                {
                    "issuer": "https://auth.example.com",
                    "authorization_endpoint": "https://auth.example.com/authorize",
                    "token_endpoint": "http://auth.example.com/token",
                },
                "token_endpoint",
            ),
            (
                "unrelated_registrable_domain_co_uk_lookalike",
                {
                    "issuer": "https://auth.example.com",
                    "authorization_endpoint": "https://auth.example.com/authorize",
                    "token_endpoint": "https://auth.evil.co.uk/token",
                },
                "token_endpoint",
            ),
        ]
    )
    def test_rejects_mismatched_endpoints(self, _name, metadata, offending_field):
        with self.assertRaises(ValueError) as ctx:
            _validate_endpoints_bound_to_issuer(metadata)
        self.assertIn(offending_field, str(ctx.exception))

    @parameterized.expand(
        [
            ("missing_issuer", {"authorization_endpoint": "https://auth.example.com/authorize"}),
            ("empty_issuer", {"issuer": "", "authorization_endpoint": "https://auth.example.com/authorize"}),
            ("relative_issuer", {"issuer": "/auth", "authorization_endpoint": "https://auth.example.com/authorize"}),
        ]
    )
    def test_rejects_invalid_issuer(self, _name, metadata):
        with self.assertRaises(ValueError):
            _validate_endpoints_bound_to_issuer(metadata)


class TestRegisterDCRClient(SimpleTestCase):
    @parameterized.expand(
        [
            ("public_client", False),
            ("confidential_client", True),
        ]
    )
    def test_rejects_explicit_unsupported_auth_methods(self, _name, has_client_secret):
        with self.assertRaisesMessage(ValueError, "private_key_jwt"):
            select_token_endpoint_auth_method(
                {"token_endpoint_auth_methods_supported": ["private_key_jwt"]},
                has_client_secret=has_client_secret,
            )

    def test_uses_public_auth_when_it_is_the_only_supported_method_with_secret(self):
        assert (
            select_token_endpoint_auth_method(
                {"token_endpoint_auth_methods_supported": ["none"]},
                has_client_secret=True,
            )
            == "none"
        )

    def test_omitted_supported_methods_default_to_basic_for_confidential_clients(self):
        assert select_token_endpoint_auth_method({}, has_client_secret=True) == "client_secret_basic"

    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_rejects_dcr_when_provider_only_lists_unsupported_auth_methods(self, mock_post):
        with self.assertRaisesMessage(ValueError, "private_key_jwt"):
            register_dcr_client(
                {
                    "registration_endpoint": "https://auth.example.com/register",
                    "token_endpoint_auth_methods_supported": ["private_key_jwt"],
                },
                "https://app.posthog.com/callback",
            )

        mock_post.assert_not_called()

    @parameterized.expand(
        [
            (
                "drops_secret_when_server_honors_public_client",
                {"client_id": "abc", "token_endpoint_auth_method": "none"},
                ("abc", None, "none"),
            ),
            (
                "drops_secret_when_server_omits_it",
                {"client_id": "abc", "token_endpoint_auth_method": "none", "client_secret": ""},
                ("abc", None, "none"),
            ),
            (
                "keeps_secret_when_server_registered_confidential_client_post",
                {
                    "client_id": "abc",
                    "client_secret": "minted-secret",
                    "token_endpoint_auth_method": "client_secret_post",
                },
                ("abc", "minted-secret", "client_secret_post"),
            ),
            (
                "keeps_secret_when_server_registered_confidential_client_basic",
                {
                    "client_id": "abc",
                    "client_secret": "minted-secret",
                    "token_endpoint_auth_method": "client_secret_basic",
                },
                ("abc", "minted-secret", "client_secret_basic"),
            ),
            (
                "keeps_secret_with_basic_auth_when_auth_method_unspecified",
                {"client_id": "abc", "client_secret": "minted-secret"},
                ("abc", "minted-secret", "client_secret_basic"),
            ),
        ]
    )
    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, ""))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_returns_client_secret_only_when_server_requires_it(
        self, _name, response_body, expected, mock_post, _allow
    ):
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 201
        mock_response.json.return_value = response_body
        mock_post.return_value = mock_response

        result = register_dcr_client(
            {"registration_endpoint": "https://auth.example.com/register"},
            "https://app.posthog.com/callback",
        )

        assert result == expected

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, ""))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_registers_refresh_grant_without_refresh_scope(self, mock_post, _allow):
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "client_id": "abc",
            "client_secret": "minted-secret",
            "token_endpoint_auth_method": "client_secret_post",
        }
        mock_post.return_value = mock_response

        result = register_dcr_client(
            {
                "registration_endpoint": "https://auth.example.com/register",
                "scopes_supported": ["read", "write"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
            },
            "https://app.posthog.com/callback",
        )

        assert result == ("abc", "minted-secret", "client_secret_post")
        payload = mock_post.call_args.kwargs["json"]
        assert payload["grant_types"] == ["authorization_code", "refresh_token"]
        assert payload["token_endpoint_auth_method"] == "client_secret_post"
        assert payload["scope"] == "read write"
        assert "refresh_token" not in payload["scope"]
        assert mock_post.call_args.kwargs["allow_redirects"] is False

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, ""))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_keeps_requested_basic_auth_when_dcr_response_omits_auth_method(self, mock_post, _allow):
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "client_id": "abc",
            "client_secret": "minted-secret",
        }
        mock_post.return_value = mock_response

        result = register_dcr_client(
            {
                "registration_endpoint": "https://auth.example.com/register",
                "token_endpoint_auth_methods_supported": ["client_secret_basic"],
            },
            "https://app.posthog.com/callback",
        )

        assert result == ("abc", "minted-secret", "client_secret_basic")
        assert mock_post.call_args.kwargs["json"]["token_endpoint_auth_method"] == "client_secret_basic"

    def test_scope_selection_prefers_protected_resource_scopes(self):
        metadata = {
            "scopes_supported": ["admin", "read"],
            "resource_scopes_supported": ["read"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "resource": "https://mcp.example.com/",
        }

        assert requested_oauth_scopes(metadata) == ["read"]
        assert requested_oauth_grant_types(metadata) == ["authorization_code", "refresh_token"]
        assert oauth_resource(metadata) == "https://mcp.example.com/"


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

        metadata, client_id, client_secret, auth_method = resolve_installation_oauth_context(installation)

        assert metadata["token_endpoint"] == "https://auth.template.example.com/token"
        assert client_id == "template-client"
        assert client_secret == "template-secret"
        assert auth_method == "client_secret_basic"

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

        metadata, client_id, client_secret, auth_method = resolve_installation_oauth_context(installation)

        assert metadata["token_endpoint"] == "https://auth.dcr-template.example.com/token"
        assert client_id == "minted-for-user"
        assert client_secret is None
        assert auth_method == "none"

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

        metadata, client_id, client_secret, auth_method = resolve_installation_oauth_context(installation)

        assert metadata["token_endpoint"] == "https://auth.custom.example.com/token"
        assert client_id == "per-user-client"
        assert client_secret == "per-user-secret"
        assert auth_method == "client_secret_basic"

    def test_custom_install_without_secret_returns_none(self):
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            url="https://mcp.custom.example.com/mcp",
            auth_type="oauth",
            oauth_metadata={"token_endpoint": "https://auth.custom.example.com/token"},
            sensitive_configuration={"dcr_client_id": "public-client"},
        )

        _metadata, _client_id, client_secret, auth_method = resolve_installation_oauth_context(installation)

        assert client_secret is None
        assert auth_method == "none"


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
    def test_confidential_custom_install_defaults_to_http_basic(self, mock_post, _allow):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
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
        sent_form = mock_post.call_args.kwargs["data"]
        assert "client_id" not in sent_form
        assert "client_secret" not in sent_form
        assert sent_form["grant_type"] == "authorization_code"
        assert sent_form["code_verifier"] == "pkce-verifier"
        assert mock_post.call_args.kwargs["auth"] == ("confidential-client", "confidential-secret")
        assert mock_post.call_args.kwargs["allow_redirects"] is False

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_client_secret_post_custom_install_sends_secret_in_form(self, mock_post, _allow):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {"access_token": "abc", "refresh_token": "def"}
        mock_post.return_value = mock_resp

        installation = self._make_installation(
            sensitive_configuration={
                "dcr_client_id": "confidential-client",
                "dcr_client_secret": "confidential-secret",
                "dcr_token_endpoint_auth_method": "client_secret_post",
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
        sent_form = mock_post.call_args.kwargs["data"]
        assert sent_form["client_id"] == "confidential-client"
        assert sent_form["client_secret"] == "confidential-secret"
        assert sent_form["grant_type"] == "authorization_code"
        assert sent_form["code_verifier"] == "pkce-verifier"
        assert mock_post.call_args.kwargs["auth"] is None

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

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_client_secret_basic_custom_install_uses_http_basic(self, mock_post, _allow):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {"access_token": "abc"}
        mock_post.return_value = mock_resp

        installation = self._make_installation(
            sensitive_configuration={
                "dcr_client_id": "basic-client",
                "dcr_client_secret": "basic-secret",
                "dcr_token_endpoint_auth_method": "client_secret_basic",
            },
        )

        exchange_oauth_token(
            installation=installation,
            code="auth-code",
            pkce_verifier="pkce-verifier",
            redirect_uri="https://app.posthog.com/callback",
            is_https=lambda url: url.startswith("https://"),
        )

        sent_form = mock_post.call_args.kwargs["data"]
        assert "client_id" not in sent_form
        assert "client_secret" not in sent_form
        assert mock_post.call_args.kwargs["auth"] == ("basic-client", "basic-secret")

    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_token_exchange_includes_resource_indicator(self, mock_post, _allow):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {"access_token": "abc"}
        mock_post.return_value = mock_resp

        installation = self._make_installation(
            sensitive_configuration={"dcr_client_id": "public-client"},
        )
        installation.oauth_metadata = {
            "token_endpoint": "https://auth.custom.example.com/token",
            "resource": "https://mcp.custom.example.com/",
        }
        installation.save(update_fields=["oauth_metadata"])

        exchange_oauth_token(
            installation=installation,
            code="auth-code",
            pkce_verifier="pkce-verifier",
            redirect_uri="https://app.posthog.com/callback",
            is_https=lambda url: url.startswith("https://"),
        )

        assert mock_post.call_args.kwargs["data"]["resource"] == "https://mcp.custom.example.com/"

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

    @parameterized.expand(
        [
            ("ok_200", 200, True, False),
            ("created_201", 201, True, False),
            ("accepted_202", 202, True, False),
            ("bad_request_400", 400, False, True),
            ("unauthorized_401", 401, False, True),
            ("unprocessable_422", 422, False, True),
            ("server_error_500", 500, False, True),
        ]
    )
    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.post")
    def test_accepts_any_2xx_status(self, _name, status_code, ok, should_raise, mock_post, _allow):
        """Some providers (e.g. Supabase) return 201 on token issue — we must accept it."""
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.ok = ok
        mock_resp.json.return_value = {"access_token": "abc", "refresh_token": "def"}
        mock_resp.text = "{}"
        mock_post.return_value = mock_resp

        installation = self._make_installation(
            sensitive_configuration={"dcr_client_id": "client"},
        )

        if should_raise:
            with self.assertRaises(OAuthTokenExchangeError):
                exchange_oauth_token(
                    installation=installation,
                    code="auth-code",
                    pkce_verifier="pkce-verifier",
                    redirect_uri="https://app.posthog.com/callback",
                    is_https=lambda url: url.startswith("https://"),
                )
        else:
            result = exchange_oauth_token(
                installation=installation,
                code="auth-code",
                pkce_verifier="pkce-verifier",
                redirect_uri="https://app.posthog.com/callback",
                is_https=lambda url: url.startswith("https://"),
            )
            assert result["access_token"] == "abc"
