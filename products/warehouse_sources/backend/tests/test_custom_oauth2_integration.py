import json
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.contrib.admin.sites import AdminSite
from django.db import IntegrityError

from parameterized import parameterized

from posthog.models import Team
from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED
from posthog.models.scoping.manager import TeamScopeError

from products.warehouse_sources.backend.admin.custom_oauth2_integration_admin import CustomOAuth2IntegrationAdmin
from products.warehouse_sources.backend.models.custom_oauth2_integration import (
    CustomOAuth2Integration,
    custom_oauth2_refresh_counter,
    get_custom_oauth2_integration,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2AuthRequestError,
)

AUTH_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth"


def _token_response(status_code: int = 200, payload: Optional[dict[str, Any]] = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    # The token exchange reads a capped `response.raw.read(...)` then json.loads — seed the raw body.
    response.raw.read.return_value = json.dumps(payload if payload is not None else {}).encode()
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

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_refresh_increments_success_and_failure_counters(self, mock_session):
        # The refresh path mirrors core OauthIntegration.refresh_access_token's observability: a
        # success/failed counter so a stuck rotating provider shows up in metrics, not just logs.
        success_before = custom_oauth2_refresh_counter.labels("success")._value.get()
        failed_before = custom_oauth2_refresh_counter.labels("failed")._value.get()

        mock_session.return_value.post.return_value = _token_response(
            payload={"access_token": "minted", "expires_in": 3600}
        )
        self._make_integration().refresh_and_persist()

        mock_session.return_value.post.return_value = _token_response(
            status_code=400, payload={"error": "invalid_grant"}
        )
        with self.assertRaises(OAuth2AuthRequestError):
            self._make_integration().refresh_and_persist()

        assert custom_oauth2_refresh_counter.labels("success")._value.get() == success_before + 1
        assert custom_oauth2_refresh_counter.labels("failed")._value.get() == failed_before + 1

    @parameterized.expand([("before_midpoint", 20, False), ("after_midpoint", 40, True)])
    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_get_access_token_refreshes_at_lifetime_midpoint(
        self, _name: str, minutes_elapsed: int, expect_refresh: bool, mock_session: MagicMock
    ):
        # Proactive half-life refresh, mirroring OauthIntegration.access_token_expired: a 60-minute token
        # is reused before its 30-minute midpoint and re-minted after it. A flat pre-expiry buffer would
        # instead reuse it until the last minute — handing a long sync a near-dead token, since the engine
        # no longer refreshes mid-sync and this up-front runway is all there is.
        mock_session.return_value.post.return_value = _token_response(
            payload={"access_token": "minted-fresh", "expires_in": 3600}
        )
        now = datetime.now(UTC)
        integration = self._make_integration(
            config={"refreshed_at": int((now - timedelta(minutes=minutes_elapsed)).timestamp())},
            sensitive_config={
                "access_token": "cached-token",
                "token_expiry": (now + timedelta(minutes=60 - minutes_elapsed)).isoformat(),
            },
        )

        token = integration.get_access_token()

        if expect_refresh:
            assert token == "minted-fresh"
            mock_session.return_value.post.assert_called_once()
        else:
            assert token == "cached-token"
            mock_session.return_value.post.assert_not_called()

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_short_lived_token_not_treated_as_expired_right_after_mint(self, mock_session):
        # Half-life refresh: a freshly-minted token sits at the very start of its lifetime, well before the
        # midpoint, so it's reused rather than re-minted — even for a very short (30s) TTL, where a flat
        # pre-expiry buffer would have read it as already-expired the instant it's minted.
        now = datetime.now(UTC)
        integration = self._make_integration(
            config={"refreshed_at": int(now.timestamp())},
            sensitive_config={
                "access_token": "short-lived",
                "token_expiry": (now + timedelta(seconds=30)).isoformat(),
            },
        )

        assert integration.get_access_token() == "short-lived"
        mock_session.return_value.post.assert_not_called()

    def test_constraint_rejects_duplicate_non_null_source_link(self):
        # The partial unique index: a second integration for the same (team, source) must be rejected.
        from products.warehouse_sources.backend.models import ExternalDataSource  # noqa: PLC0415

        source = ExternalDataSource.objects.create(
            team=self.team, source_id="sid", connection_id="cid", status="Completed", source_type="Stripe"
        )
        CustomOAuth2Integration.objects.for_team(self.team.pk).create(team=self.team, external_data_source=source)

        with self.assertRaises(IntegrityError):
            CustomOAuth2Integration.objects.for_team(self.team.pk).create(team=self.team, external_data_source=source)

    def test_constraint_allows_multiple_null_source_rows(self):
        # The condition excludes NULL source links, so unlinked rows (pre-create token stores) don't
        # collide — the plain UniqueConstraint would also allow this, but only by accident of NULL
        # distinctness; this pins the intended behaviour.
        self._make_integration()
        self._make_integration()  # would raise without the partial condition only if NULLs collided

        assert (
            CustomOAuth2Integration.objects.for_team(self.team.pk).filter(external_data_source__isnull=True).count()
            == 2
        )

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

    def test_admin_get_queryset_reads_outside_team_scope(self):
        # Django admin runs outside request/team scope, so the model's fail-closed default manager would
        # raise TeamScopeError the moment the changelist evaluates the queryset. The admin's get_queryset()
        # reads through unscoped() instead; this guards against that escape hatch being dropped.
        integration = self._make_integration()
        admin_instance = CustomOAuth2IntegrationAdmin(CustomOAuth2Integration, AdminSite())

        rows = list(admin_instance.get_queryset(MagicMock()))

        assert integration.pk in {row.pk for row in rows}
