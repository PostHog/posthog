from django.db import transaction

from posthog.models.integration import Integration, OauthIntegration


def resolve_ebay_oauth_token(integration_id: int, team_id: int, current_token: str | None = None) -> str:
    """Return a valid eBay access token, refreshing through the integration row when needed.

    eBay user access tokens last two hours, which a large backfill outlives, so the token has to be
    re-minted mid-sync. ``current_token`` is the token the caller was rejected on: when the row still
    holds it, nobody else has refreshed yet and we do it; otherwise a parallel schema sync already
    refreshed and its fresher token is handed back. The row lock keeps those parallel syncs from
    stampeding the token endpoint.
    """
    with transaction.atomic():
        integration = Integration.objects.select_for_update().get(id=integration_id, team_id=team_id, kind="ebay")
        oauth = OauthIntegration(integration)
        if oauth.access_token_expired() or (current_token is not None and integration.access_token == current_token):
            oauth.refresh_access_token()
        token = integration.access_token

    if not token:
        raise ValueError("eBay access token not found")
    return token
