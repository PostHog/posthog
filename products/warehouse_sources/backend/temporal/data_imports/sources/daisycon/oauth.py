from datetime import UTC, datetime, timedelta

from django.db import transaction

from requests import PreparedRequest

from posthog.models.integration import Integration, OauthIntegration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase

# Daisycon access tokens live 30 minutes. Re-mint well before that so no request carries an expired token.
_DAISYCON_TOKEN_REFRESH_AFTER = timedelta(minutes=20)


def resolve_daisycon_oauth_token(integration_id: int, team_id: int, current_token: str | None = None) -> str:
    """Return a valid Daisycon access token, refreshing under a row lock when needed.

    Daisycon refresh tokens are single-use and rotate on every refresh. Parallel schema syncs share
    one integration, so the refresh is serialized with `select_for_update`, and the row is reloaded
    inside the lock: a sync that lost the race picks up the token another sync already rotated
    instead of spending the old refresh token again. `refresh_access_token` persists the rotation.

    `current_token` is the token the caller just used. When it still matches the row, nobody else
    rotated past it, so this call refreshes.
    """
    with transaction.atomic():
        integration = Integration.objects.select_for_update().get(id=integration_id, team_id=team_id, kind="daisycon")
        oauth = OauthIntegration(integration)
        if oauth.access_token_expired() or (current_token is not None and integration.access_token == current_token):
            oauth.refresh_access_token()
        token = integration.access_token

    if not token:
        raise ValueError("Daisycon access token not found")
    return token


class DaisyconIntegrationAuth(AuthConfigBase):
    """Bearer auth that re-mints the Daisycon access token through the integration row.

    The framework's in-process `OAuth2Auth` cannot persist a rotated refresh token, so the refresh
    goes through the row instead (see `resolve_daisycon_oauth_token`). The auth refreshes before the
    token expires, so a long sync never sees a 401 from an expired token, and a 401 stays a reliable
    sign that the grant itself is gone.
    """

    def __init__(self, integration_id: int, team_id: int, access_token: str) -> None:
        self._integration_id = integration_id
        self._team_id = team_id
        self.token: str = access_token
        self._refresh_after: datetime = datetime.now(UTC) + _DAISYCON_TOKEN_REFRESH_AFTER

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        if datetime.now(UTC) >= self._refresh_after:
            self.token = resolve_daisycon_oauth_token(self._integration_id, self._team_id, self.token)
            self._refresh_after = datetime.now(UTC) + _DAISYCON_TOKEN_REFRESH_AFTER
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.token,) if self.token else ()
