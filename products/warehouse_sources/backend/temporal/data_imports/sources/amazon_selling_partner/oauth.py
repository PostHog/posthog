from collections.abc import Callable

from django.db import transaction

from posthog.models.integration import AMAZON_SELLING_PARTNER_CONSENT_HOSTS, Integration, OauthIntegration

AccessTokenProvider = Callable[[bool], str]


def resolve_amazon_selling_partner_token(integration_id: int, team_id: int, force_refresh: bool = False) -> str:
    """Return a valid SP-API access token, minting a fresh one under a row lock when needed.

    Login with Amazon rate limits its token endpoint, and the schemas of one source sync in parallel
    off the same integration, so refreshes have to be serialized rather than raced. ``select_for_update``
    gives that lock, and reloading inside it means a sync that lost the race picks up the token the
    winner already minted instead of spending another mint on the same grant.
    """
    with transaction.atomic():
        integration = Integration.objects.select_for_update().get(
            id=integration_id, team_id=team_id, kind__in=list(AMAZON_SELLING_PARTNER_CONSENT_HOSTS)
        )
        oauth = OauthIntegration(integration)
        if force_refresh or oauth.access_token_expired():
            oauth.refresh_access_token()
        token = integration.access_token

    if not token:
        raise ValueError("Amazon Selling Partner access token not found")
    return token


def amazon_selling_partner_token_provider(integration_id: int, team_id: int) -> AccessTokenProvider:
    """Bind an integration to a callable the transport can use to (re-)read its access token."""

    def provider(force_refresh: bool = False) -> str:
        return resolve_amazon_selling_partner_token(integration_id, team_id, force_refresh=force_refresh)

    return provider
