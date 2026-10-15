import time

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.daisycon.oauth import (
    DAISYCON_GRANT_REVOKED_ERROR,
    DaisyconTokenRefreshError,
    resolve_daisycon_oauth_token,
)


@override_settings(DAISYCON_APP_CLIENT_ID="daisycon-client-id", DAISYCON_APP_CLIENT_SECRET="daisycon-client-secret")
class TestResolveDaisyconOauthToken(BaseTest):
    def _integration(self, refreshed_seconds_ago: int, **config: object) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="daisycon",
            integration_id=f"publishers:{refreshed_seconds_ago}",
            config={"expires_in": 1800, "refreshed_at": int(time.time()) - refreshed_seconds_ago, **config},
            sensitive_config={"refresh_token": "rt_1", "access_token": "at_1"},
        )

    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
    def test_keeps_a_token_with_half_its_life_left_and_rotates_an_older_one(
        self, mock_post: MagicMock, _mock_reload: MagicMock
    ) -> None:
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.json.return_value = {"access_token": "at_2", "refresh_token": "rt_2"}
        fresh = self._integration(refreshed_seconds_ago=600)
        stale = self._integration(refreshed_seconds_ago=1000)

        assert resolve_daisycon_oauth_token(fresh.id, self.team.id) == "at_1"
        assert resolve_daisycon_oauth_token(stale.id, self.team.id) == "at_2"
        assert mock_post.call_count == 1
        stale.refresh_from_db()
        assert stale.sensitive_config["refresh_token"] == "rt_2"

    @parameterized.expand(
        [
            # A timeout or 5xx can clear, so the run fails with a retryable error rather than a 401.
            ("transient", 503, {"error": "unavailable"}, {}, DaisyconTokenRefreshError, "did not refresh"),
            # The fifth invalid_grant in a row marks the grant dead, which only a reconnect fixes.
            (
                "revoked",
                400,
                {"error": "invalid_grant"},
                {"refresh_invalid_grant_count": 4},
                ValueError,
                DAISYCON_GRANT_REVOKED_ERROR,
            ),
        ]
    )
    @patch("posthog.models.integration.oauth.requests.post")
    def test_a_failed_refresh_never_hands_back_the_expired_token(
        self,
        _name: str,
        status: int,
        body: dict,
        config: dict,
        expected: type[Exception],
        message: str,
        mock_post: MagicMock,
    ) -> None:
        mock_post.return_value = MagicMock(status_code=status, text="")
        mock_post.return_value.json.return_value = body
        integration = self._integration(refreshed_seconds_ago=3600, **config)

        with pytest.raises(expected, match=message):
            resolve_daisycon_oauth_token(integration.id, self.team.id)

        # The failure bookkeeping survives the raise, so repeated invalid_grant reaches the terminal state.
        integration.refresh_from_db()
        assert integration.config["refresh_failure_count"] == 1
