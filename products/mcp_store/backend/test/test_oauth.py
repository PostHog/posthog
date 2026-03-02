from urllib.parse import urlparse

from unittest.mock import MagicMock, patch

from django.test import TestCase

import requests
from parameterized import parameterized

from products.mcp_store.backend.oauth import (
    TIMEOUT,
    SSRFBlockedError,
    TokenRefreshError,
    discover_oauth_metadata,
    refresh_oauth_token,
    register_dcr_client,
)


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
                "spoofed_issuer_rejected",
                {
                    "issuer": "https://accounts.notion.com",
                    "authorization_endpoint": "https://evil.com/authorize",
                    "token_endpoint": "https://evil.com/token",
                },
                "https://evil.com/mcp",
                True,
            ),
            (
                "matching_issuer_accepted",
                {
                    "issuer": "https://evil.com",
                    "authorization_endpoint": "https://evil.com/authorize",
                    "token_endpoint": "https://evil.com/token",
                },
                "https://evil.com/mcp",
                False,
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
            ),
            (
                "no_issuer_defaults_to_origin",
                {
                    "authorization_endpoint": "https://example.com/authorize",
                    "token_endpoint": "https://example.com/token",
                },
                "https://example.com/mcp",
                False,
            ),
        ]
    )
    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.get")
    def test_step2_fallback_issuer_validation(self, _name, auth_metadata, server_url, should_raise, mock_get, _allow):
        not_found = self._make_response(ok=False, status_code=404)
        auth_resp = self._make_response(json_data=auth_metadata)
        mock_get.side_effect = [not_found, not_found, auth_resp]
        expected_origin = self._origin(server_url)
        expected_path = urlparse(server_url).path.rstrip("/")
        expected_urls = [
            f"{expected_origin}/.well-known/oauth-protected-resource{expected_path}",
            f"{expected_origin}/.well-known/oauth-protected-resource",
            self._auth_metadata_url(expected_origin),
        ]

        if should_raise:
            with self.assertRaisesRegex(ValueError, "Issuer mismatch"):
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
            ),
            (
                "spoofed_issuer_rejected",
                "https://auth.example.com",
                {
                    "issuer": "https://evil.com",
                    "authorization_endpoint": "https://evil.com/authorize",
                    "token_endpoint": "https://evil.com/token",
                },
                True,
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
            ),
        ]
    )
    @patch("products.mcp_store.backend.oauth.is_url_allowed", return_value=(True, None))
    @patch("products.mcp_store.backend.oauth.requests.get")
    def test_step1_protected_resource_issuer_validation(
        self, _name, auth_server_url, auth_metadata, should_raise, mock_get, _allow
    ):
        resource_resp = self._make_response(json_data={"authorization_servers": [auth_server_url]})
        auth_resp = self._make_response(json_data=auth_metadata)
        mock_get.side_effect = [resource_resp, auth_resp]
        mcp_url = "https://mcp.example.com/mcp"
        expected_urls = [
            "https://mcp.example.com/.well-known/oauth-protected-resource/mcp",
            self._auth_metadata_url(auth_server_url),
        ]

        if should_raise:
            with self.assertRaisesRegex(ValueError, "Issuer mismatch"):
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
