from unittest.mock import MagicMock, patch

from django.test import TestCase

import requests
from parameterized import parameterized

from products.mcp_store.backend.oauth import (
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
