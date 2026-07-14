"""
Signed identity tokens for push subscription registration.

A push device token (FCM registration token / APNs device token) is a delivery *address*, not a
credential: FCM/APNs hand a token to any app instance that registers, and an attacker owns their own
token legitimately. So possession of a token proves "deliver to this device" — never "this device
belongs to user X". Binding a token to a `distinct_id` therefore needs proof that the caller is
allowed to act for that `distinct_id`. The public project token can't provide it: it is embedded in
the mobile app and world-readable, so anyone can present it and claim any `distinct_id`.

Following the pattern proven by Braze's "SDK Authentication", the customer's backend — the only party
that actually authenticated the end user — mints a short-lived token asserting the user's
`distinct_id`, signed with the project's secret API key. PostHog re-verifies the signature at
registration time. An attacker holding only the public project token cannot forge it.

We use symmetric HMAC (HS256) keyed by `Team.secret_api_token` rather than an asymmetric key pair:
PostHog verifies its own ingestion, so there is no third-party verifier that would need a public key,
and the secret already ships with built-in rotation via `secret_api_token_backup`. Verification
accepts either the current or the backup secret so a key rotation doesn't reject in-flight tokens.
"""

from datetime import UTC, datetime, timedelta

import jwt

from posthog.models.team.team import Team

PUSH_IDENTITY_TOKEN_AUDIENCE = "posthog:push_identity"
_ALGORITHM = "HS256"

# Short TTL: the token only needs to survive the round trip from the customer's backend, through the
# app, to the registration call. Keeping it small bounds the replay window (a replay can only re-assert
# the same (distinct_id, app_id) binding the legitimate user already holds, so the value is low anyway).
DEFAULT_TTL = timedelta(minutes=5)


def sign_push_identity_token(
    secret_api_token: str,
    distinct_id: str,
    app_id: str,
    ttl: timedelta = DEFAULT_TTL,
) -> str:
    """Mint a signed identity token.

    This is the reference implementation of what the *customer's backend* runs after it has
    authenticated the end user. It is not called by PostHog's own ingestion (which only verifies);
    it lives here so the signing and verification rules stay in one place and the tests can exercise
    the real round trip.
    """
    return jwt.encode(
        {
            "sub": distinct_id,
            "app_id": app_id,
            "aud": PUSH_IDENTITY_TOKEN_AUDIENCE,
            "exp": datetime.now(UTC) + ttl,
        },
        secret_api_token,
        algorithm=_ALGORITHM,
    )


def verify_push_identity_token(token: str, team: Team, distinct_id: str, app_id: str) -> bool:
    """Return True iff `token` is a valid, unexpired identity assertion for exactly this
    `(distinct_id, app_id)`, signed by the team's current or backup secret API key.

    Binding the claim to `app_id` as well as `distinct_id` stops a token minted for one app being
    replayed to register a device under a different app in the same project.
    """
    candidate_secrets = [secret for secret in (team.secret_api_token, team.secret_api_token_backup) if secret]
    for secret in candidate_secrets:
        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=[_ALGORITHM],
                audience=PUSH_IDENTITY_TOKEN_AUDIENCE,
            )
        except jwt.InvalidTokenError:
            continue
        if payload.get("sub") == distinct_id and payload.get("app_id") == app_id:
            return True
    return False
