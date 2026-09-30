from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models import OAuthAccessToken, OAuthApplication, Team, User

from products.webmcp.backend.logic.mcp_server import WebMCPProxy, resolve_mcp_url
from products.webmcp.backend.logic.tokens import WEBMCP_OAUTH_CLIENT_ID, WebMCPTokenIssuer


def create_webmcp_app(scopes: list[str] | None = None) -> OAuthApplication:
    return OAuthApplication.objects.create(
        name="PostHog WebMCP",
        client_id=WEBMCP_OAUTH_CLIENT_ID,
        client_type=OAuthApplication.CLIENT_PUBLIC,
        authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
        redirect_uris="https://us.posthog.com/webmcp/callback",
        algorithm="RS256",
        is_cimd_client=True,
        scopes=scopes or [],
    )


def mcp_response(status_code: int, payload: dict) -> MagicMock:
    response = MagicMock(status_code=status_code, ok=200 <= status_code < 300)
    response.json.return_value = payload
    return response


class TestResolveMcpUrl(SimpleTestCase):
    @parameterized.expand(
        [
            ("us", "US", False, "https://mcp.us.posthog.com/mcp"),
            ("eu", "EU", False, "https://mcp.eu.posthog.com/mcp"),
            ("self_hosted", None, False, None),
            ("local_dev", None, True, "http://localhost:8787/mcp"),
        ]
    )
    def test_resolves_the_mcp_server_for_the_instance(
        self, _name: str, region: str | None, debug: bool, expected: str | None
    ) -> None:
        with override_settings(CLOUD_DEPLOYMENT=region, DEBUG=debug):
            assert resolve_mcp_url() == expected


class TestWebMCPTokenIssuer(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.app = create_webmcp_app(scopes=["insight:read", "insight:write"])
        self.issuer = WebMCPTokenIssuer(self.app)

    def test_reuses_a_live_token_for_the_same_team(self) -> None:
        first = self.issuer.get_or_mint(self.user, self.team.id)

        assert self.issuer.get_or_mint(self.user, self.team.id) == first
        token = OAuthAccessToken.objects.get(token=first)
        assert token.scoped_teams == [self.team.id]
        assert token.scope == "insight:read insight:write"

    @parameterized.expand(
        [
            ("other_team", "other_team", timedelta(hours=1), None),
            ("near_expiry", "same_team", timedelta(minutes=5), None),
            ("impersonated", "same_team", timedelta(hours=1), "impersonator"),
        ]
    )
    def test_does_not_reuse_token(self, _name: str, team: str, expires_in: timedelta, impersonator: str | None) -> None:
        other_team = Team.objects.create(organization=self.organization)
        existing = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.app,
            token="pha_existing_webmcp_token",
            expires=timezone.now() + expires_in,
            scope="insight:read",
            scoped_teams=[other_team.id if team == "other_team" else self.team.id],
            impersonated_by=User.objects.create(email="staff@example.com") if impersonator else None,
        )

        minted = self.issuer.get_or_mint(self.user, self.team.id)

        assert minted != existing.token
        assert OAuthAccessToken.objects.get(token=minted).scoped_teams == [self.team.id]


class TestWebMCPProxy(BaseTest):
    @patch("products.webmcp.backend.logic.mcp_server.requests.post")
    def test_mints_a_fresh_token_when_the_reused_one_is_rejected(self, mock_post: MagicMock) -> None:
        issuer = WebMCPTokenIssuer(create_webmcp_app())
        revoked = issuer.get_or_mint(self.user, self.team.id)
        mock_post.side_effect = [
            mcp_response(401, {"error": "invalid_token"}),
            mcp_response(
                200,
                {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "ok"}]}},
            ),
        ]

        result = WebMCPProxy(self.user, self.team.id, issuer=issuer, url="http://mcp.test/mcp").run_exec("tools")

        assert result.content == [{"type": "text", "text": "ok"}]
        assert result.is_error is False
        authorizations = [call.kwargs["headers"]["Authorization"] for call in mock_post.call_args_list]
        assert authorizations[0] == f"Bearer {revoked}"
        assert authorizations[1] != authorizations[0]
