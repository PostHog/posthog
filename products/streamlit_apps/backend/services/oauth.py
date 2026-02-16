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
ACCESS_TOKEN_EXPIRY_SECONDS = 60 * 60  # 1 hour
# Bridge tokens live longer than the user's iframe token because they back the
# in-sandbox HogQL shim for the entire sandbox lifetime (15 min TTL + buffer).
BRIDGE_TOKEN_EXPIRY_SECONDS = 60 * 20


@lru_cache(maxsize=1)
def get_streamlit_oauth_app() -> OAuthApplication:
    """Return the pre-seeded Streamlit OAuth application.

    The row is created by migration 0004_seed_streamlit_oauth_app. We cache it
    here because (a) the row never changes during a process lifetime and (b)
    every connect_info / sandbox start hits this lookup.
    """
    return OAuthApplication.objects.get(name=STREAMLIT_OAUTH_APP_NAME)


def create_streamlit_access_token(user: User, team_id: int) -> str:
    """Mint an OAuth access token scoped to the given team.

    The token can be validated via PostHog's /oauth/introspect endpoint
    (self-introspection — no extra credentials needed).
    """
    oauth_app = get_streamlit_oauth_app()
    token_value = generate_random_oauth_access_token(None)

    OAuthAccessToken.objects.create(
        application=oauth_app,
        token=token_value,
        user=user,
        expires=timezone.now() + timedelta(seconds=ACCESS_TOKEN_EXPIRY_SECONDS),
        scope="query:read",
        scoped_teams=[team_id],
    )

    return token_value


def find_reusable_streamlit_access_token(user: User, team_id: int, min_remaining_seconds: int = 300) -> str | None:
    """Return an existing non-near-expiry token for (user, team) if one exists.

    Used by `connect_info` to avoid minting a fresh token on every poll. Only
    returns tokens that have at least `min_remaining_seconds` left so the
    iframe doesn't immediately have to refresh.
    """
    oauth_app = get_streamlit_oauth_app()
    cutoff = timezone.now() + timedelta(seconds=min_remaining_seconds)
    token = (
        OAuthAccessToken.objects.filter(
            application=oauth_app,
            user=user,
            scoped_teams=[team_id],
            expires__gt=cutoff,
        )
        .order_by("-expires")
        .first()
    )
    return token.token if token else None


def create_sandbox_bridge_token(user: User | None, team_id: int) -> str:
    """Mint a long-TTL OAuth token for the sandbox→PostHog HogQL bridge hop.

    Lifetime matches the sandbox TTL plus a buffer. The token is delivered to
    the sandbox via a file in /run/bridge_token (read once, then unlinked) so
    it never appears in /proc/<pid>/environ.
    """
    oauth_app = get_streamlit_oauth_app()
    token_value = generate_random_oauth_access_token(None)

    OAuthAccessToken.objects.create(
        application=oauth_app,
        token=token_value,
        user=user,
        expires=timezone.now() + timedelta(seconds=BRIDGE_TOKEN_EXPIRY_SECONDS),
        scope="query:read",
        scoped_teams=[team_id],
    )
    return token_value
