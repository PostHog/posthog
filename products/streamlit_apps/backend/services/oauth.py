from __future__ import annotations

from datetime import timedelta
from functools import lru_cache

from django.utils import timezone

import structlog

from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.user import User
from posthog.models.utils import generate_random_oauth_access_token

logger = structlog.get_logger(__name__)

STREAMLIT_OAUTH_APP_NAME = "PostHog Streamlit Apps"
# Seeded by migration 0002; looked up by this stable field, not the editable name.
STREAMLIT_OAUTH_CLIENT_ID = "posthog-streamlit-apps-first-party"
ACCESS_TOKEN_EXPIRY_SECONDS = 60 * 60  # 1 hour
BRIDGE_TOKEN_EXPIRY_SECONDS = 60 * 20  # sandbox TTL + buffer

# streamlit:iframe and streamlit:bridge suffixes let the proxy and the bridge
# refuse tokens of the opposite type even if they leak between contexts.
IFRAME_TOKEN_SCOPE = "query:read streamlit:iframe"
BRIDGE_TOKEN_SCOPE = "query:read streamlit:bridge"


@lru_cache(maxsize=1)
def get_streamlit_oauth_app() -> OAuthApplication:
    """Return the pre-seeded Streamlit OAuth application (cached per process)."""
    return OAuthApplication.objects.get(client_id=STREAMLIT_OAUTH_CLIENT_ID)


def create_streamlit_access_token(user: User, team_id: int) -> OAuthAccessToken:
    """Mint an iframe OAuth access token scoped to the given team.

    Returns the ORM object so callers can read the real `expires` timestamp
    instead of reporting the minting TTL.
    """
    oauth_app = get_streamlit_oauth_app()
    token_value = generate_random_oauth_access_token(None)

    return OAuthAccessToken.objects.create(
        application=oauth_app,
        token=token_value,
        user=user,
        expires=timezone.now() + timedelta(seconds=ACCESS_TOKEN_EXPIRY_SECONDS),
        scope=IFRAME_TOKEN_SCOPE,
        scoped_teams=[team_id],
    )


def find_reusable_streamlit_access_token(
    user: User, team_id: int, min_remaining_seconds: int = 300
) -> OAuthAccessToken | None:
    """Return a non-near-expiry iframe token for (user, team), or None.

    Filters on IFRAME_TOKEN_SCOPE so bridge tokens can't be reused here.
    """
    oauth_app = get_streamlit_oauth_app()
    cutoff = timezone.now() + timedelta(seconds=min_remaining_seconds)
    return (
        OAuthAccessToken.objects.filter(
            application=oauth_app,
            user=user,
            scoped_teams=[team_id],
            scope=IFRAME_TOKEN_SCOPE,
            expires__gt=cutoff,
        )
        .order_by("-expires")
        .first()
    )


def create_sandbox_bridge_token(user: User | None, team_id: int) -> str:
    """Mint a long-TTL OAuth token for the sandbox→PostHog HogQL bridge hop."""
    oauth_app = get_streamlit_oauth_app()
    token_value = generate_random_oauth_access_token(None)

    OAuthAccessToken.objects.create(
        application=oauth_app,
        token=token_value,
        user=user,
        expires=timezone.now() + timedelta(seconds=BRIDGE_TOKEN_EXPIRY_SECONDS),
        scope=BRIDGE_TOKEN_SCOPE,
        scoped_teams=[team_id],
    )
    return token_value
