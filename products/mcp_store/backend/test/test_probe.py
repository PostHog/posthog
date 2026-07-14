import json
from urllib.parse import parse_qs, urlparse

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import requests
from parameterized import parameterized

from posthog.security.pinned_requests import SSRFBlockedError

from products.mcp_store.backend.probe import ProbeResult, probe_mcp_server

SERVER_URL = "https://mcp.example.com/mcp"
ORIGIN = "https://mcp.example.com"

INITIALIZE_MESSAGE = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "serverInfo": {"name": "test-server", "version": "1.0"},
    },
}

PROTECTED_RESOURCE_URL = f"{ORIGIN}/.well-known/oauth-protected-resource/mcp"
AUTH_SERVER_METADATA_URL = f"{ORIGIN}/.well-known/oauth-authorization-server"
REGISTRATION_URL = f"{ORIGIN}/register"
AUTHORIZE_URL = f"{ORIGIN}/authorize"

PROTECTED_RESOURCE_BODY = {"resource": SERVER_URL, "authorization_servers": [ORIGIN]}
AUTH_SERVER_METADATA_BODY = {
    "issuer": ORIGIN,
    "authorization_endpoint": AUTHORIZE_URL,
    "token_endpoint": f"{ORIGIN}/token",
    "registration_endpoint": REGISTRATION_URL,
}


def _mock_response(status_code=200, *, json_body=None, text="", content_type="application/json", headers=None):
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.headers = {"Content-Type": content_type, **(headers or {})}
    if json_body is not None:
        response.text = json.dumps(json_body)
        response.json.return_value = json_body
    else:
        response.text = text
        response.json.side_effect = ValueError("not json")
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status_code}", response=response)
    else:
        response.raise_for_status.return_value = None
    return response


def _url_router(routes):
    def handle(url, *args, **kwargs):
        handler = routes.get(url.split("?")[0])
        if handler is None:
            return _mock_response(404, text="not found", content_type="text/plain")
        if isinstance(handler, Exception):
            raise handler
        return handler

    return handle


class TestProbeMCPServer(SimpleTestCase):
    def _probe(self, *, post_routes, get_routes=None):
        post_router = _url_router(post_routes)
        get_router = _url_router(get_routes or {})

        # probe.py and oauth.py both send every outbound request through
        # pinned_request; patch each module's reference with the same
        # method-dispatching router so a URL behaves identically on either path.
        def pinned_router(method, url, **kwargs):
            return post_router(url) if method == "POST" else get_router(url)

        with (
            patch("products.mcp_store.backend.probe.pinned_request", side_effect=pinned_router) as pinned,
            patch("products.mcp_store.backend.oauth.pinned_request", side_effect=pinned_router) as oauth_pinned,
        ):
            result = probe_mcp_server(SERVER_URL)
        return result, oauth_pinned, pinned

    @parameterized.expand(
        [
            ("json_response", "application/json", json.dumps(INITIALIZE_MESSAGE)),
            ("sse_response", "text/event-stream", f"event: message\ndata: {json.dumps(INITIALIZE_MESSAGE)}\n\n"),
        ]
    )
    def test_open_server_happy_path(self, _name, content_type, body):
        result, _oauth, _pinned = self._probe(
            post_routes={SERVER_URL: _mock_response(200, text=body, content_type=content_type)},
        )

        self.assertTrue(result.reachable)
        self.assertTrue(result.speaks_mcp)
        self.assertEqual(result.server_info, {"name": "test-server", "version": "1.0"})
        self.assertEqual(result.auth_flavor, "open")
        self.assertIsNone(result.oauth_metadata)
        self.assertEqual(result.errors, [])
        self.assertTrue(result.passed_activation_gate)

    def test_oauth_dcr_full_pass(self):
        result, _oauth, pinned = self._probe(
            post_routes={
                SERVER_URL: _mock_response(401, text="unauthorized", content_type="text/plain"),
                REGISTRATION_URL: _mock_response(
                    201, json_body={"client_id": "minted-client-id", "token_endpoint_auth_method": "none"}
                ),
            },
            get_routes={
                PROTECTED_RESOURCE_URL: _mock_response(200, json_body=PROTECTED_RESOURCE_BODY),
                AUTH_SERVER_METADATA_URL: _mock_response(200, json_body=AUTH_SERVER_METADATA_BODY),
                AUTHORIZE_URL: _mock_response(200, text="<html>log in</html>", content_type="text/html"),
            },
        )

        self.assertTrue(result.reachable)
        self.assertTrue(result.speaks_mcp)
        self.assertEqual(result.auth_flavor, "oauth_dcr")
        self.assertTrue(result.dcr_registered)
        self.assertTrue(result.authorize_endpoint_ok)
        self.assertEqual(result.oauth_metadata["registration_endpoint"], REGISTRATION_URL)
        self.assertTrue(result.passed_activation_gate)

        authorize_calls = [c for c in pinned.call_args_list if c.args[1].startswith(f"{AUTHORIZE_URL}?")]
        self.assertEqual(len(authorize_calls), 1)
        query = parse_qs(urlparse(authorize_calls[0].args[1]).query)
        self.assertEqual(query["client_id"], ["minted-client-id"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertIn("code_challenge", query)
        self.assertTrue(query["redirect_uri"][0].endswith("/api/mcp_store/oauth_redirect/"))

    def test_oauth_without_registration_endpoint_is_oauth_shared(self):
        metadata = {k: v for k, v in AUTH_SERVER_METADATA_BODY.items() if k != "registration_endpoint"}
        result, _oauth, _pinned = self._probe(
            post_routes={SERVER_URL: _mock_response(401, text="unauthorized", content_type="text/plain")},
            get_routes={
                PROTECTED_RESOURCE_URL: _mock_response(200, json_body=PROTECTED_RESOURCE_BODY),
                AUTH_SERVER_METADATA_URL: _mock_response(200, json_body=metadata),
            },
        )

        self.assertTrue(result.speaks_mcp)
        self.assertEqual(result.auth_flavor, "oauth_shared")
        self.assertFalse(result.dcr_registered)
        self.assertFalse(result.authorize_endpoint_ok)
        self.assertEqual(result.oauth_metadata["token_endpoint"], f"{ORIGIN}/token")
        self.assertFalse(result.passed_activation_gate)

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_auth_required_without_metadata_is_api_key_or_unknown(self, _name, status_code):
        result, _oauth, _pinned = self._probe(
            post_routes={SERVER_URL: _mock_response(status_code, text="denied", content_type="text/plain")},
        )

        self.assertTrue(result.reachable)
        self.assertTrue(result.speaks_mcp)
        self.assertEqual(result.auth_flavor, "api_key_or_unknown")
        self.assertIsNone(result.oauth_metadata)
        self.assertFalse(result.dcr_registered)
        self.assertTrue(any(error.startswith("OAuth discovery failed") for error in result.errors))
        self.assertTrue(result.passed_activation_gate)

    @parameterized.expand(
        [
            ("html_200", lambda: _mock_response(200, text="<html>a docs page</html>", content_type="text/html"), True),
            ("not_found", lambda: _mock_response(404, text="not found", content_type="text/plain"), True),
            ("connection_error", lambda: requests.ConnectionError("connection refused"), False),
        ]
    )
    def test_non_mcp_endpoint(self, _name, response_factory, expected_reachable):
        result, _oauth, _pinned = self._probe(post_routes={SERVER_URL: response_factory()})

        self.assertIs(result.reachable, expected_reachable)
        self.assertFalse(result.speaks_mcp)
        self.assertIsNone(result.server_info)
        self.assertEqual(len(result.errors), 1)
        self.assertFalse(result.passed_activation_gate)

    def test_initialize_url_blocked_by_ssrf(self):
        result, _oauth, _pinned = self._probe(
            post_routes={SERVER_URL: SSRFBlockedError("Disallowed target IP: 10.0.0.5")},
        )

        self.assertFalse(result.reachable)
        self.assertFalse(result.speaks_mcp)
        self.assertTrue(any(error.startswith("MCP server URL blocked by SSRF protection") for error in result.errors))
        self.assertFalse(result.passed_activation_gate)

    def test_initialize_redirect_is_not_followed(self):
        result, _oauth, pinned = self._probe(
            post_routes={
                SERVER_URL: _mock_response(
                    302, text="", content_type="text/plain", headers={"Location": "http://169.254.169.254/latest/"}
                )
            },
        )

        self.assertTrue(result.reachable)
        self.assertFalse(result.speaks_mcp)
        self.assertTrue(any("redirect" in error for error in result.errors))
        self.assertFalse(result.passed_activation_gate)
        # The redirect target must never be requested.
        self.assertEqual(pinned.call_count, 1)

    def test_authorize_redirect_to_blocked_target_fails_gate(self):
        blocked_url = "http://169.254.169.254/latest/"
        result, _oauth, _pinned = self._probe(
            post_routes={
                SERVER_URL: _mock_response(401, text="unauthorized", content_type="text/plain"),
                REGISTRATION_URL: _mock_response(
                    201, json_body={"client_id": "minted-client-id", "token_endpoint_auth_method": "none"}
                ),
            },
            get_routes={
                PROTECTED_RESOURCE_URL: _mock_response(200, json_body=PROTECTED_RESOURCE_BODY),
                AUTH_SERVER_METADATA_URL: _mock_response(200, json_body=AUTH_SERVER_METADATA_BODY),
                AUTHORIZE_URL: _mock_response(
                    307, text="", content_type="text/plain", headers={"Location": blocked_url}
                ),
                blocked_url: SSRFBlockedError("Local/metadata host"),
            },
        )

        self.assertEqual(result.auth_flavor, "oauth_dcr")
        self.assertTrue(result.dcr_registered)
        self.assertFalse(result.authorize_endpoint_ok)
        self.assertTrue(
            any(error.startswith("Authorization endpoint blocked by SSRF protection") for error in result.errors)
        )
        self.assertFalse(result.passed_activation_gate)

    @parameterized.expand(
        [
            ("registration_http_500", lambda: _mock_response(500, text="boom", content_type="text/plain")),
            ("registration_missing_client_id", lambda: _mock_response(201, json_body={"scope": "read"})),
        ]
    )
    def test_dcr_registration_failure_falls_back_to_oauth_shared(self, _name, registration_response_factory):
        result, _oauth, _pinned = self._probe(
            post_routes={
                SERVER_URL: _mock_response(401, text="unauthorized", content_type="text/plain"),
                REGISTRATION_URL: registration_response_factory(),
            },
            get_routes={
                PROTECTED_RESOURCE_URL: _mock_response(200, json_body=PROTECTED_RESOURCE_BODY),
                AUTH_SERVER_METADATA_URL: _mock_response(200, json_body=AUTH_SERVER_METADATA_BODY),
            },
        )

        self.assertEqual(result.auth_flavor, "oauth_shared")
        self.assertFalse(result.dcr_registered)
        self.assertFalse(result.authorize_endpoint_ok)
        self.assertTrue(any("Dynamic Client Registration" in error for error in result.errors))
        self.assertFalse(result.passed_activation_gate)

    def test_probe_never_raises_on_unexpected_error(self):
        result, _oauth, _pinned = self._probe(post_routes={SERVER_URL: RuntimeError("boom")})

        self.assertFalse(result.reachable)
        self.assertFalse(result.speaks_mcp)
        self.assertTrue(any(error.startswith("Probe aborted unexpectedly") for error in result.errors))
        self.assertFalse(result.passed_activation_gate)


class TestPassedActivationGate(SimpleTestCase):
    @parameterized.expand(
        [
            ("open_reachable_mcp", "open", True, True, False, False, True),
            ("open_not_mcp", "open", True, False, False, False, False),
            ("open_unreachable", "open", False, False, False, False, False),
            ("api_key_reachable_mcp", "api_key_or_unknown", True, True, False, False, True),
            ("oauth_dcr_full_pass", "oauth_dcr", True, True, True, True, True),
            ("oauth_dcr_authorize_down", "oauth_dcr", True, True, True, False, False),
            ("oauth_dcr_not_registered", "oauth_dcr", True, True, False, True, False),
            ("oauth_shared", "oauth_shared", True, True, False, False, False),
        ]
    )
    def test_gate(self, _name, auth_flavor, reachable, speaks_mcp, dcr_registered, authorize_endpoint_ok, expected):
        result = ProbeResult(
            reachable=reachable,
            speaks_mcp=speaks_mcp,
            auth_flavor=auth_flavor,
            dcr_registered=dcr_registered,
            authorize_endpoint_ok=authorize_endpoint_ok,
        )
        self.assertIs(result.passed_activation_gate, expected)
