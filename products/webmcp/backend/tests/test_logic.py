from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

import requests
from parameterized import parameterized

from posthog.models import OAuthAccessToken, OAuthApplication, Team, User
from posthog.temporal.oauth import WEBMCP_APP_CLIENT_ID

from products.webmcp.backend.facade import api
from products.webmcp.backend.facade.contracts import CallToolInput, McpServerError, McpServerTimeout, ToolCallResult
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


@override_settings(MCP_SERVER_URL="https://mcp.example.com/mcp")
@patch("products.webmcp.backend.logic.mcp_server.requests.post")
class TestWebMCPCallTool(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch(
            "products.webmcp.backend.logic.tokens.get_or_create_cimd_application", return_value=create_webmcp_app()
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @parameterized.expand(
        [
            (
                # Exec appends a session metadata block, which must not read as the tool's result.
                "json_result",
                {
                    "content": [
                        {"type": "text", "text": '{"id":7,"active":true}'},
                        {"type": "text", "text": '{"conversation_id":"c-1"}'},
                    ]
                },
                ToolCallResult(
                    structured_content={"id": 7, "active": True}, text='{"id":7,"active":true}', is_error=False
                ),
            ),
            (
                "tool_error",
                {
                    "content": [{"type": "text", "text": "Error: [feature-flag-enable]: version conflict"}],
                    "isError": True,
                },
                ToolCallResult(
                    structured_content=None, text="Error: [feature-flag-enable]: version conflict", is_error=True
                ),
            ),
        ]
    )
    def test_calls_the_named_tool_through_exec(
        self, mock_post: MagicMock, _name: str, result: dict, expected: ToolCallResult
    ) -> None:
        mock_post.return_value = mcp_response(200, {"jsonrpc": "2.0", "id": 1, "result": result})

        outcome = api.call_tool(
            CallToolInput(user_id=self.user.id, team_id=self.team.id, tool="feature-flag-enable", arguments={"id": 7})
        )

        assert outcome == expected
        # Without --json most tools answer with formatted text that the caller cannot parse.
        assert mock_post.call_args.kwargs["json"]["params"]["arguments"] == {
            "command": 'call --json --confirm feature-flag-enable {"id":7}'
        }

    def test_refuses_a_tool_name_that_would_change_the_command(self, mock_post: MagicMock) -> None:
        with self.assertRaises(McpServerError):
            api.call_tool(
                CallToolInput(
                    user_id=self.user.id, team_id=self.team.id, tool="feature-flags-list\ncall x", arguments={}
                )
            )

        mock_post.assert_not_called()

    @parameterized.expand(
        [
            ("read_timeout", requests.ReadTimeout(), McpServerTimeout),
            # A connect timeout never reached the server, so the call is safe to retry.
            ("connect_timeout", requests.ConnectTimeout(), McpServerError),
        ]
    )
    def test_only_a_read_timeout_leaves_the_outcome_unknown(
        self, mock_post: MagicMock, _name: str, error: Exception, expected: type[McpServerError]
    ) -> None:
        mock_post.side_effect = error

        with self.assertRaises(McpServerError) as raised:
            api.call_tool(
                CallToolInput(
                    user_id=self.user.id, team_id=self.team.id, tool="feature-flag-enable", arguments={"id": 7}
                )
            )

        assert type(raised.exception) is expected
