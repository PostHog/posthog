from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models import OAuthAccessToken, OAuthApplication, Team, User
from posthog.temporal.oauth import WEBMCP_APP_CLIENT_ID

from products.webmcp.backend.facade import api
from products.webmcp.backend.logic.tokens import WebMCPTokenIssuer


def create_webmcp_app(scopes: list[str] | None = None) -> OAuthApplication:
    return OAuthApplication.objects.create(
        name="PostHog WebMCP",
        client_id=WEBMCP_APP_CLIENT_ID,
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


class TestWebMCPAvailability(SimpleTestCase):
    @parameterized.expand(
        [
            ("https", "https://mcp.example.com/mcp", False, True),
            ("plain_http", "http://mcp.example.com/mcp", False, False),
            ("plain_http_in_debug", "http://localhost:8787/mcp", True, True),
            ("unset", "", False, False),
        ]
    )
    def test_is_available(self, _name: str, url: str, debug: bool, expected: bool) -> None:
        with override_settings(MCP_SERVER_URL=url, DEBUG=debug):
            assert api.is_available() is expected
