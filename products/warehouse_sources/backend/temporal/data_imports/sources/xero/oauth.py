from datetime import UTC, datetime, timedelta

from django.db import transaction

from requests import PreparedRequest

from posthog.models.integration import Integration, OauthIntegration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase

# Xero access tokens live 30 minutes, so re-check the row well before one expires mid-sync.
_XERO_TOKEN_RECHECK_AFTER = timedelta(minutes=10)


def resolve_xero_oauth_token(integration_id: int, team_id: int, current_token: str | None = None) -> str:
    """Return a valid Xero access token, refreshing under a row lock when needed.

    Xero rotates the refresh token on every refresh, so a refresh must persist the new refresh
    token, which `refresh_access_token` does. Parallel schema syncs share one integration, so the
    refresh holds a row lock and reloads the row inside it. A sync that lost the race then uses the
    token another sync already minted instead of spending the old refresh token again.

    `current_token` is the token the caller used last. When the row still holds it, the caller
    asked for a fresh one, so refresh. Otherwise return the newer token on the row.
    """
    with transaction.atomic():
        integration = Integration.objects.select_for_update().get(id=integration_id, team_id=team_id, kind="xero")
        oauth = OauthIntegration(integration)
        if oauth.access_token_expired() or (current_token is not None and integration.access_token == current_token):
            oauth.refresh_access_token()
        token = integration.access_token

    if not token:
        raise ValueError("Xero access token not found")
    return token


class XeroIntegrationAuth(AuthConfigBase):
    """Bearer auth that re-mints the Xero access token through the integration row.

    The framework's in-process OAuth2 auth cannot persist a rotated refresh token, so this auth
    refreshes through the row (see `resolve_xero_oauth_token`) before the 30-minute expiry.
    """

    def __init__(self, integration_id: int, team_id: int, access_token: str) -> None:
        self._integration_id = integration_id
        self._team_id = team_id
        self.token: str = access_token
        self._recheck_after: datetime = datetime.now(UTC) + _XERO_TOKEN_RECHECK_AFTER

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        if datetime.now(UTC) >= self._recheck_after:
            self.token = resolve_xero_oauth_token(self._integration_id, self._team_id, self.token)
            self._recheck_after = datetime.now(UTC) + _XERO_TOKEN_RECHECK_AFTER
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.token,) if self.token else ()
