import time

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.xero.oauth import resolve_xero_oauth_token


class TestResolveXeroOauthToken(BaseTest):
    @parameterized.expand(
        [
            ("caller_token_still_current", "at_1", True, "at_new"),
            ("row_already_rotated", "at_old", False, "at_1"),
        ]
    )
    def test_refreshes_only_when_the_row_still_holds_the_callers_token(
        self, _name: str, current_token: str, expect_refresh: bool, expected_token: str
    ) -> None:
        integration = Integration.objects.create(
            team=self.team,
            kind="xero",
            integration_id="user-123",
            config={"expires_in": 1800, "refreshed_at": int(time.time())},
            sensitive_config={"access_token": "at_1", "refresh_token": "rt_1"},
        )

        def rotate(oauth_integration) -> None:
            oauth_integration.integration.sensitive_config = {"access_token": "at_new", "refresh_token": "rt_2"}

        with patch(
            "posthog.models.integration.oauth.OauthIntegration.refresh_access_token", autospec=True, side_effect=rotate
        ) as refresh:
            token = resolve_xero_oauth_token(integration.id, self.team.id, current_token)

        assert refresh.called is expect_refresh
        assert token == expected_token
