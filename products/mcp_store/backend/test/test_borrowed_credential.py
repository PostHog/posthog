import json
import base64

from django.test import SimpleTestCase, override_settings

import jwt
from parameterized import parameterized

from products.mcp_store.backend.borrowed_credential import is_posthog_connection

THIRD_PARTY_URL = "https://mcp.linear.app/mcp"
SITE_URL = "https://app.posthog.example"


def _access_token_jwt(issuer: str) -> str:
    return jwt.encode({"iss": issuer, "sub": "user"}, "k" * 32, algorithm="HS256", headers={"typ": "at+jwt"})


def _unsigned_access_token_jwt(claims: dict) -> str:
    def segment(value: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    return f"{segment({'alg': 'HS256', 'typ': 'at+jwt'})}.{segment(claims)}.c2ln"


@override_settings(SITE_URL=SITE_URL, MCP_SERVER_URL="https://mcp.posthog.example/mcp", ID_JAG_ALLOWED_RESOURCES=[])
class TestIsPostHogConnection(SimpleTestCase):
    @parameterized.expand(
        [
            ("oauth_access_token", THIRD_PARTY_URL, "pha_" + "x" * 40, True),
            ("personal_api_key", THIRD_PARTY_URL, "phx_" + "x" * 40, True),
            ("project_secret_key", THIRD_PARTY_URL, "phs_" + "x" * 40, True),
            ("access_token_jwt_issued_here", THIRD_PARTY_URL, _access_token_jwt(SITE_URL), True),
            (
                "access_token_jwt_from_a_third_party",
                THIRD_PARTY_URL,
                _access_token_jwt("https://auth.linear.app"),
                False,
            ),
            (
                "access_token_jwt_with_a_non_text_issuer",
                THIRD_PARTY_URL,
                _unsigned_access_token_jwt({"iss": 42}),
                False,
            ),
            ("posthog_cloud_host", "https://mcp.posthog.com/mcp", "opaque-token", True),
            ("posthog_cloud_host_without_a_token", "https://mcp-eu.posthog.com/mcp", None, True),
            ("posthog_cloud_host_with_root_dot", "https://mcp.posthog.com./mcp", "opaque-token", True),
            (
                "posthog_cloud_host_in_fullwidth_characters",
                "https://ｍｃｐ．ｐｏｓｔｈｏｇ．ｃｏｍ/mcp",
                "opaque-token",
                True,
            ),
            ("this_instance_mcp_server", "https://mcp.posthog.example/mcp", "opaque-token", True),
            ("this_instance_mcp_server_with_default_port", "https://mcp.posthog.example:443/mcp", "opaque-token", True),
            ("this_instance_mcp_server_on_another_port", "https://mcp.posthog.example:8443/mcp", "opaque-token", False),
            ("lookalike_host", "https://notposthog.com/mcp", "opaque-token", False),
            ("third_party_token", THIRD_PARTY_URL, "sk-linear-abc123", False),
            ("third_party_without_a_token", THIRD_PARTY_URL, None, False),
        ]
    )
    def test_classifies_connection(self, _name: str, url: str, token: str | None, expected: bool):
        assert is_posthog_connection(url, token) is expected
