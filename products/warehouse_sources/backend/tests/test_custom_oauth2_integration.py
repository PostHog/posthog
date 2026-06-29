from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.models import Team
from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED
from posthog.models.scoping.manager import TeamScopeError

from products.warehouse_sources.backend.models.custom_oauth2_integration import (
    CustomOAuth2Integration,
    get_custom_oauth2_integration,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2AuthRequestError,
)

AUTH_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth"


def _token_response(status_code: int = 200, payload: Optional[dict[str, Any]] = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else {}
    return response


class TestCustomOAuth2Integration(BaseTest):
    def _make_integration(
        self,
        *,
        team: Optional[Team] = None,
        config: Optional[dict[str, Any]] = None,
        sensitive_config: Optional[dict[str, Any]] = None,
    ) -> CustomOAuth2Integration:
        team = team or self.team
        base_config = {"token_url": "https://auth.example.com/token", "client_id": "cid", "grant_type": "refresh_token"}
        base_secrets = {"client_secret": "csecret", "refresh_token": "refresh-orig"}
        return CustomOAuth2Integration.objects.for_team(team.pk).create(
            team=team,
            config={**base_config, **(config or {})},
            sensitive_config={**base_secrets, **(sensitive_config or {})},
        )

    def _reload(self, integration: CustomOAuth2Integration) -> CustomOAuth2Integration:
        # The fail-closed manager rejects refresh_from_db() (no team context in a plain test), so re-fetch
        # through for_team to prove the values actually hit the DB rather than only the in-memory instance.
        return CustomOAuth2Integration.objects.for_team(integration.team_id).get(pk=integration.pk)

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_refresh_and_persist_writes_rotated_refresh_token(self, mock_session):
        # The Calendly bug this model exists to fix: the provider rotates the single-use refresh token on
        # every mint, so the new one must be persisted or the next sync fails with invalid_grant.
        mock_session.return_value.post.return_value = _token_response(
            payload={"access_token": "minted-1", "expires_in": 3600, "refresh_token": "refresh-rotated"}
        )
        integration = self._make_integration()

        token = integration.refresh_and_persist()

        assert token == "minted-1"
        fresh = self._reload(integration)
        assert fresh.sensitive_config["refresh_token"] == "refresh-rotated"
        assert fresh.sensitive_config["access_token"] == "minted-1"
        assert fresh.sensitive_config["token_expiry"] is not None
        assert fresh.config["refreshed_at"] > 0
        assert fresh.errors == ""

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_refresh_and_persist_keeps_refresh_token_when_not_rotated(self, mock_session):
        # A non-rotating provider returns no refresh_token in the response; the stored one must survive
        # untouched (a stray overwrite to None would break the next refresh).
        mock_session.return_value.post.return_value = _token_response(
            payload={"access_token": "minted-2", "expires_in": 3600}
        )
        integration = self._make_integration()

        integration.refresh_and_persist()

        fresh = self._reload(integration)
        assert fresh.sensitive_config["refresh_token"] == "refresh-orig"
        assert fresh.sensitive_config["access_token"] == "minted-2"

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_refresh_and_persist_marks_error_and_preserves_token_on_failure(self, mock_session):
        # A token-endpoint rejection (e.g. an expired refresh token) must surface the broken-token state
        # via errors without clobbering the stored refresh token — re-entry replaces it later.
        mock_session.return_value.post.return_value = _token_response(
            status_code=400, payload={"error": "invalid_grant", "error_description": "expired"}
        )
        integration = self._make_integration()

        with self.assertRaises(OAuth2AuthRequestError):
            integration.refresh_and_persist()

        fresh = self._reload(integration)
        assert fresh.errors == ERROR_TOKEN_REFRESH_FAILED
        assert fresh.sensitive_config["refresh_token"] == "refresh-orig"
        assert "access_token" not in fresh.sensitive_config

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_get_access_token_reuses_valid_cached_token_without_minting(self, mock_session):
        # The reuse gate: a still-valid cached token is returned as-is, minting nothing. This is what
        # caps refresh-token rotation churn for high-frequency syncs.
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        integration = self._make_integration(sensitive_config={"access_token": "cached-token", "token_expiry": future})

        assert integration.get_access_token() == "cached-token"
        mock_session.return_value.post.assert_not_called()

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_get_access_token_refreshes_expired_cached_token(self, mock_session):
        # The other side of the gate: a stale cached token forces a fresh mint, which is persisted.
        mock_session.return_value.post.return_value = _token_response(
            payload={"access_token": "minted-fresh", "expires_in": 3600}
        )
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        integration = self._make_integration(sensitive_config={"access_token": "stale-token", "token_expiry": past})

        assert integration.get_access_token() == "minted-fresh"
        mock_session.return_value.post.assert_called_once()
        assert self._reload(integration).sensitive_config["access_token"] == "minted-fresh"

    def test_team_scoping_is_fail_closed(self):
        integration = self._make_integration()
        other_team = Team.objects.create(organization=self.organization, name="other")
        other_integration = self._make_integration(team=other_team)

        # No team context set → the fail-closed manager refuses to return rows.
        with self.assertRaises(TeamScopeError):
            CustomOAuth2Integration.objects.get(pk=integration.pk)

        # The helper scopes to a team and never crosses to another team's row.
        assert get_custom_oauth2_integration(str(integration.pk), self.team.pk).pk == integration.pk
        with self.assertRaises(CustomOAuth2Integration.DoesNotExist):
            get_custom_oauth2_integration(str(other_integration.pk), self.team.pk)
