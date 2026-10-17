import time

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.xero.oauth import (
    XeroTokenRefreshError,
    resolve_xero_oauth_token,
)


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

    @parameterized.expand(
        [
            ("transient_failure_on_an_expiring_token", 3600, False, XeroTokenRefreshError, None),
            ("terminal_failure_on_an_expiring_token", 3600, True, ValueError, None),
            ("failure_with_less_time_left_than_the_next_recheck", 22 * 60, False, XeroTokenRefreshError, None),
            ("failure_while_the_token_outlasts_the_next_recheck", 0, False, None, "at_1"),
        ]
    )
    def test_failed_refresh(
        self,
        _name: str,
        token_age_seconds: int,
        terminal: bool,
        expected_error: type[Exception] | None,
        expected_token: str | None,
    ) -> None:
        integration = Integration.objects.create(
            team=self.team,
            kind="xero",
            integration_id="user-123",
            config={"expires_in": 1800, "refreshed_at": int(time.time()) - token_age_seconds},
            sensitive_config={"access_token": "at_1", "refresh_token": "rt_1"},
        )

        def fail(oauth_integration) -> None:
            oauth_integration.integration.errors = "TOKEN_REFRESH_FAILED"
            if terminal:
                oauth_integration.integration.config["refresh_terminal"] = True

        with patch(
            "posthog.models.integration.oauth.OauthIntegration.refresh_access_token", autospec=True, side_effect=fail
        ):
            if expected_error is not None:
                with self.assertRaises(expected_error):
                    resolve_xero_oauth_token(integration.id, self.team.id, "at_1")
            else:
                assert resolve_xero_oauth_token(integration.id, self.team.id, "at_1") == expected_token
