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

Two signing schemes are accepted, checked in this order:

1. Asymmetric ES256 (preferred). The customer holds an EC (P-256) private key and registers only the
   public key on the push channel (`config["push_identity_public_keys"]`). PostHog verifies with the
   public key and never stores a usable signing secret. This matches how Braze and OneSignal secure
   device registration, and it works for projects that only ever created scoped, hashed-at-rest API
   keys (which can't be used for HMAC).
2. Symmetric HS256 keyed by `Team.secret_api_token` (legacy). Kept so integrations set up before
   asymmetric support keep working; accepts the current or backup secret so rotation doesn't reject
   in-flight tokens. `Team.secret_api_token` is the deprecated "feature flags secure API key", so new
   setups should prefer the asymmetric path.

The two algorithms are verified strictly separately (a public key is only ever tried with ES256, a
secret only with HS256) to close the classic JWT algorithm-confusion attack.
"""

from datetime import UTC, datetime, timedelta

import jwt

from posthog.models.team.team import Team

PUSH_IDENTITY_TOKEN_AUDIENCE = "posthog:push_identity"
_HMAC_ALGORITHM = "HS256"
_ASYMMETRIC_ALGORITHM = "ES256"

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
    return _claims(distinct_id, app_id, ttl, secret_api_token, _HMAC_ALGORITHM)


def sign_push_identity_token_es256(
    private_key_pem: str,
    distinct_id: str,
    app_id: str,
    ttl: timedelta = DEFAULT_TTL,
) -> str:
    """Reference ES256 signer: what the customer's backend runs with its EC private key. PostHog only
    ever verifies (against the registered public key); this lives here so the round trip stays testable.
    """
    return _claims(distinct_id, app_id, ttl, private_key_pem, _ASYMMETRIC_ALGORITHM)


def _claims(distinct_id: str, app_id: str, ttl: timedelta, key: str, algorithm: str) -> str:
    return jwt.encode(
        {
            "sub": distinct_id,
            "app_id": app_id,
            "aud": PUSH_IDENTITY_TOKEN_AUDIENCE,
            "exp": datetime.now(UTC) + ttl,
        },
        key,
        algorithm=algorithm,
    )


def verify_push_identity_token(
    token: str,
    team: Team,
    distinct_id: str,
    app_id: str,
    public_keys: list[str] | None = None,
) -> bool:
    """Return True iff `token` is a valid, unexpired identity assertion for exactly this
    `(distinct_id, app_id)`.

    Tries each registered EC public key with ES256 first, then falls back to the team's current/backup
    secret with HS256. Binding the claim to `app_id` as well as `distinct_id` stops a token minted for
    one app being replayed to register a device under a different app in the same project.
    """
    for public_key in public_keys or []:
        if _decode_matches(token, public_key, _ASYMMETRIC_ALGORITHM, distinct_id, app_id):
            return True
    for secret in (team.secret_api_token, team.secret_api_token_backup):
        if secret and _decode_matches(token, secret, _HMAC_ALGORITHM, distinct_id, app_id):
            return True
    return False


def _decode_matches(token: str, key: str, algorithm: str, distinct_id: str, app_id: str) -> bool:
    # One algorithm per key type, never a list: verifying an HS256 token with a public key (or vice
    # versa) is the JWT algorithm-confusion attack, so the two schemes are checked in separate passes.
    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=[algorithm],
            audience=PUSH_IDENTITY_TOKEN_AUDIENCE,
            # Require exp explicitly: PyJWT only checks expiry when the claim is present, so without
            # this a token minted (by an external signer) with no exp would never expire.
            options={"require": ["exp"]},
        )
    except jwt.PyJWTError:
        # PyJWTError covers both InvalidTokenError (bad/expired/wrong-signature token) and InvalidKeyError
        # (the key can't be used with this algorithm, e.g. a non-P-256 EC key against ES256). Treat every
        # such case as "not verified" and fail closed, rather than letting InvalidKeyError 500 the endpoint.
        return False
    return payload.get("sub") == distinct_id and payload.get("app_id") == app_id
