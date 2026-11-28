from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.sources.google_admob.google_admob import AdMobAuthError
from products.warehouse_sources.sources.google_admob.source import (
    RECONNECT_MESSAGE,
    AdMobTokenRefreshError,
    GoogleAdMobSource,
)
from products.warehouse_sources.sources.sdk import ERROR_TOKEN_REFRESH_FAILED, IntegrationAccountListingError
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, always, scripted_network

SOURCE_MODULE = "products.warehouse_sources.sources.google_admob.source"


def _integration(kind: str = "google-admob", **attributes: Any) -> mock.MagicMock:
    integration = mock.MagicMock(kind=kind, access_token="access-token", errors="", config={})
    for name, value in attributes.items():
        setattr(integration, name, value)
    return integration


class TestAccessToken:
    def test_rejects_an_integration_of_another_provider(self) -> None:
        with (
            mock.patch.object(GoogleAdMobSource, "get_oauth_integration", return_value=_integration(kind="slack")),
            mock.patch(f"{SOURCE_MODULE}.OauthIntegration") as oauth,
            pytest.raises(ValueError, match="Integration not found: 7"),
        ):
            GoogleAdMobSource().access_token(7, team_id=1)

        # The other provider's token is never refreshed through this source.
        oauth.assert_not_called()

    @parameterized.expand(
        [
            ("dead_grant_asks_to_reconnect", {"refresh_terminal": True}, AdMobAuthError, RECONNECT_MESSAGE),
            ("passing_failure_is_retried", {}, AdMobTokenRefreshError, "The sync will retry"),
        ]
    )
    def test_failed_refresh(self, _name: str, config: dict[str, Any], error: type[Exception], message: str) -> None:
        oauth = mock.MagicMock()
        oauth.access_token_expired.return_value = True
        oauth.refresh_access_token.return_value = _integration(errors=ERROR_TOKEN_REFRESH_FAILED, config=config)

        with (
            mock.patch.object(GoogleAdMobSource, "get_oauth_integration", return_value=_integration()),
            mock.patch(f"{SOURCE_MODULE}.OauthIntegration", return_value=oauth),
            pytest.raises(error, match=message),
        ):
            GoogleAdMobSource().access_token(1, team_id=1)

        # Only the reconnect message switches the sync off; a passing failure must not match it.
        assert (message in RECONNECT_MESSAGE) is (error is AdMobAuthError)


class TestOauthAccounts:
    def test_google_outage_gives_a_listing_error_rather_than_a_crash(self) -> None:
        with (
            mock.patch.object(GoogleAdMobSource, "access_token", return_value="access-token"),
            scripted_network(always(ScriptedResponse(status=503, json={"error": {"status": "UNAVAILABLE"}}))),
            pytest.raises(IntegrationAccountListingError, match="having trouble responding"),
        ):
            GoogleAdMobSource().get_oauth_accounts(1, team_id=1)
