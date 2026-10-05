from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import requests
from parameterized import parameterized

from products.mcp_store.backend.oauth import (
    SSRFBlockedError,
    _resolve_issuer,
    _validate_endpoints_bound_to_issuer,
    discover_oauth_metadata,
    register_dcr_client,
)


class TestResolveIssuer(SimpleTestCase):
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


class TestAuthServerMetadataDiscoveryChain(SimpleTestCase):
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


class TestSSRFProtection(SimpleTestCase):
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


class TestValidateEndpointsBoundToIssuer(SimpleTestCase):
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
