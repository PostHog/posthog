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
# Deterministic client_id — seeded by migration 0002_seed_streamlit_oauth_app.
# We look the row up by this field (not by `name`, which is user-editable via
# the admin) so the lookup is guaranteed single-row and stable across renames.
STREAMLIT_OAUTH_CLIENT_ID = "posthog-streamlit-apps-first-party"
ACCESS_TOKEN_EXPIRY_SECONDS = 60 * 60  # 1 hour
# Bridge tokens live longer than the user's iframe token because they back the
# in-sandbox HogQL shim for the entire sandbox lifetime (15 min TTL + buffer).
BRIDGE_TOKEN_EXPIRY_SECONDS = 60 * 20

# Split scopes: iframe-bound tokens (sent to the browser URL) and bridge-bound
# tokens (injected into the sandbox /run/bridge_token file) must be
# non-interchangeable. Both carry query:read because the back-end HogQL API
# uses that scope for permission checks, but the additional streamlit:iframe
# / streamlit:bridge suffix lets the proxy and the bridge refuse tokens of
# the opposite type even if they leak. Scopes are stored as a
# space-separated string per OAuth 2.0 RFC 6749 §3.3.
IFRAME_TOKEN_SCOPE = "query:read streamlit:iframe"
BRIDGE_TOKEN_SCOPE = "query:read streamlit:bridge"


@lru_cache(maxsize=1)
def get_streamlit_oauth_app() -> OAuthApplication:
    """Return the pre-seeded Streamlit OAuth application.

    The row is created by migration 0002_seed_streamlit_oauth_app. We cache it
    here because (a) the row never changes during a process lifetime and (b)
    every connect_info / sandbox start hits this lookup.
    """
    return OAuthApplication.objects.get(client_id=STREAMLIT_OAUTH_CLIENT_ID)


def create_streamlit_access_token(user: User, team_id: int) -> OAuthAccessToken:
    """Mint an iframe OAuth access token scoped to the given team.

    Returned as the ORM object (not just the string) so callers can read
    the real `expires` timestamp for connect_info responses, rather than
    reporting a hardcoded ACCESS_TOKEN_EXPIRY_SECONDS that drifts as soon
    as we reuse a token mid-lifetime.

    The token can be validated via PostHog's /oauth/introspect endpoint
    (self-introspection — no extra credentials needed).
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
    """Return an existing non-near-expiry iframe token for (user, team) if
    one exists. Filters on the full IFRAME_TOKEN_SCOPE so bridge tokens
    (scoped streamlit:bridge) can never be picked up for iframe reuse.

    Used by `connect_info` to avoid minting a fresh token on every poll. Only
    returns tokens that have at least `min_remaining_seconds` left so the
    iframe doesn't immediately have to refresh.
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
    """Mint a long-TTL OAuth token for the sandbox→PostHog HogQL bridge hop.

    Lifetime matches the sandbox TTL plus a buffer. The token is delivered to
    the sandbox via a file in /run/bridge_token (read once, then unlinked) so
    it never appears in /proc/<pid>/environ.

    Carries BRIDGE_TOKEN_SCOPE so the bridge view can refuse iframe-scoped
    tokens even if they leak from browser history/referrer.
    """
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
