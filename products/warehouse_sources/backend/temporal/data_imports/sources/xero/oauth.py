from datetime import UTC, datetime, timedelta

from django.db import transaction

from requests import PreparedRequest

from posthog.models.integration import Integration, OauthIntegration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase

# Xero access tokens live 30 minutes, so re-check the row well before one expires mid-sync.
_XERO_TOKEN_RECHECK_AFTER = timedelta(minutes=10)
# A failed refresh raises when the old token could expire before the next recheck, so this margin
# must exceed the recheck interval.
_XERO_TOKEN_EXPIRY_MARGIN = _XERO_TOKEN_RECHECK_AFTER + timedelta(minutes=2)

XERO_RECONNECT_REQUIRED_MESSAGE = "Xero no longer accepts this connection. Reconnect your Xero account."


class XeroTokenRefreshError(Exception):
    """Xero did not refresh the access token for a reason that can pass, so the sync retries."""


def resolve_xero_oauth_token(integration_id: int, team_id: int, current_token: str | None = None) -> str:
    """Return a valid Xero access token, refreshing under a row lock when needed.

    Xero rotates the refresh token on every refresh, so a refresh must persist the new refresh
    token, which `refresh_access_token` does. Parallel schema syncs share one integration, so the
    refresh holds a row lock and reloads the row inside it. A sync that lost the race then uses the
    token another sync already minted instead of spending the old refresh token again.

    `current_token` is the token the caller used last. When the row still holds it, the caller
    asked for a fresh one, so refresh. Otherwise return the newer token on the row.
    """
    refresh_failed = False
    with transaction.atomic():
        integration = Integration.objects.select_for_update().get(id=integration_id, team_id=team_id, kind="xero")
        oauth = OauthIntegration(integration)
        if oauth.access_token_expired() or (current_token is not None and integration.access_token == current_token):
            oauth.refresh_access_token()
            # A failed refresh records itself on the row and returns, leaving the old token.
            refresh_failed = bool(integration.errors) and oauth.access_token_expired(_XERO_TOKEN_EXPIRY_MARGIN)
        token = integration.access_token
        terminal = bool(integration.config.get("refresh_terminal"))

    # Raised after the block, so the failure the refresh recorded on the row is committed.
    if refresh_failed and terminal:
        raise ValueError(XERO_RECONNECT_REQUIRED_MESSAGE)
    if refresh_failed:
        raise XeroTokenRefreshError("Xero did not refresh the access token. The sync will retry.")
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
