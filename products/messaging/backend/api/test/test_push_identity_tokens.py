import hmac
import json
import base64
import hashlib
from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from parameterized import parameterized

from posthog.models.team.team import Team

from products.messaging.backend.api.push_identity_tokens import (
    PUSH_IDENTITY_TOKEN_AUDIENCE,
    sign_push_identity_token,
    sign_push_identity_token_es256,
    verify_push_identity_token,
)


# A fresh EC P-256 keypair as (private PEM, public PEM): the customer's signing key and the public
# half they register with PostHog.
def _es256_keypair() -> tuple[str, str]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private_pem, public_pem


# Hand-roll an HS256 JWT: PyJWT refuses to sign HMAC with a PEM public key (it blocks alg confusion at
# the encode step), so an attacker crafting this token wouldn't use PyJWT either.
def _forge_hs256(secret: str, claims: dict) -> str:
    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    signing_input = f"{b64(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())}.{b64(json.dumps(claims).encode())}"
    signature = b64(hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest())
    return f"{signing_input}.{signature}"


# Realistic length (>= 32 bytes) — matches a real phs_ secret and avoids PyJWT's short-key warning.
CURRENT_SECRET = "phs_current_secret_0123456789abcdef0123"
BACKUP_SECRET = "phs_backup_secret_0123456789abcdef01234"
DISTINCT_ID = "user-1"
APP_ID = "my-firebase-project"


class TestPushIdentityTokens(SimpleTestCase):
    def _team(self, secret: str | None = CURRENT_SECRET, backup: str | None = None) -> Team:
        return Team(secret_api_token=secret, secret_api_token_backup=backup)

    def test_verifies_a_token_signed_with_the_current_secret(self):
        token = sign_push_identity_token(CURRENT_SECRET, DISTINCT_ID, APP_ID)
        assert verify_push_identity_token(token, self._team(), DISTINCT_ID, APP_ID) is True

    def test_verifies_a_token_signed_with_the_backup_secret_after_rotation(self):
        token = sign_push_identity_token(BACKUP_SECRET, DISTINCT_ID, APP_ID)
        team = self._team(secret=CURRENT_SECRET, backup=BACKUP_SECRET)
        assert verify_push_identity_token(token, team, DISTINCT_ID, APP_ID) is True

    @parameterized.expand(
        [
            ("wrong_distinct_id", "someone-else", APP_ID),
            ("wrong_app_id", DISTINCT_ID, "other-app"),
        ]
    )
    def test_rejects_a_token_whose_claims_do_not_match_the_registration(self, _name, sub, app_id):
        # The rebind guard: a token minted for one (distinct_id, app_id) cannot authorize a different one.
        token = sign_push_identity_token(CURRENT_SECRET, sub, app_id)
        assert verify_push_identity_token(token, self._team(), DISTINCT_ID, APP_ID) is False

    def test_rejects_a_token_signed_with_a_different_secret(self):
        token = sign_push_identity_token("phs_attacker_secret_0123456789abcdef012", DISTINCT_ID, APP_ID)
        assert verify_push_identity_token(token, self._team(), DISTINCT_ID, APP_ID) is False

    def test_rejects_an_expired_token(self):
        token = sign_push_identity_token(CURRENT_SECRET, DISTINCT_ID, APP_ID, ttl=timedelta(seconds=-1))
        assert verify_push_identity_token(token, self._team(), DISTINCT_ID, APP_ID) is False

    def test_rejects_a_token_with_no_exp_claim(self):
        # An external signer (customer backend / SDK) could omit exp; without requiring it a token would
        # never expire, so the verifier must reject it even though the signature is valid.
        token = jwt.encode(
            {"sub": DISTINCT_ID, "app_id": APP_ID, "aud": PUSH_IDENTITY_TOKEN_AUDIENCE},
            CURRENT_SECRET,
            algorithm="HS256",
        )
        assert verify_push_identity_token(token, self._team(), DISTINCT_ID, APP_ID) is False

    def test_rejects_a_malformed_token(self):
        assert verify_push_identity_token("not-a-jwt", self._team(), DISTINCT_ID, APP_ID) is False

    def test_rejects_when_the_team_has_no_secret_configured(self):
        token = sign_push_identity_token(CURRENT_SECRET, DISTINCT_ID, APP_ID)
        assert verify_push_identity_token(token, self._team(secret=None), DISTINCT_ID, APP_ID) is False

    # --- Asymmetric ES256: the customer signs with a private key, PostHog holds only the public key ---

    def test_verifies_an_es256_token_signed_by_the_registered_public_key(self):
        private_pem, public_pem = _es256_keypair()
        token = sign_push_identity_token_es256(private_pem, DISTINCT_ID, APP_ID)
        team = self._team(secret=None)  # no shared secret: only the public-key path can accept it
        assert verify_push_identity_token(token, team, DISTINCT_ID, APP_ID, public_keys=[public_pem]) is True

    def test_rejects_an_es256_token_when_a_different_public_key_is_registered(self):
        signer_private, _ = _es256_keypair()
        _, registered_public = _es256_keypair()
        token = sign_push_identity_token_es256(signer_private, DISTINCT_ID, APP_ID)
        team = self._team(secret=None)
        assert verify_push_identity_token(token, team, DISTINCT_ID, APP_ID, public_keys=[registered_public]) is False

    def test_returns_false_without_crashing_for_a_mismatched_curve_public_key(self):
        # A registered key on the wrong curve makes jwt.decode raise InvalidKeyError, which is not an
        # InvalidTokenError. verify must treat it as unverified rather than let it crash the endpoint.
        private_pem, _ = _es256_keypair()
        token = sign_push_identity_token_es256(private_pem, DISTINCT_ID, APP_ID)
        p384_public = (
            ec.generate_private_key(ec.SECP384R1())
            .public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode()
        )
        assert (
            verify_push_identity_token(token, self._team(secret=None), DISTINCT_ID, APP_ID, public_keys=[p384_public])
            is False
        )

    def test_falls_back_to_the_shared_secret_when_public_keys_are_also_registered(self):
        # A project mid-migration can carry both a legacy secret and registered public keys; a token
        # signed with the secret must still verify so existing integrations keep working.
        _, public_pem = _es256_keypair()
        token = sign_push_identity_token(CURRENT_SECRET, DISTINCT_ID, APP_ID)
        assert verify_push_identity_token(token, self._team(), DISTINCT_ID, APP_ID, public_keys=[public_pem]) is True

    def test_rejects_hs256_token_forged_with_the_public_key_as_the_hmac_secret(self):
        # JWT algorithm confusion: the public key is public, so an attacker can sign an HS256 token
        # using it as the HMAC secret. Verifying a public key only under ES256 rejects this; allowing
        # both algorithms per key would let anyone forge an identity for any distinct_id.
        _, public_pem = _es256_keypair()
        forged = _forge_hs256(
            public_pem,
            {
                "sub": DISTINCT_ID,
                "app_id": APP_ID,
                "aud": PUSH_IDENTITY_TOKEN_AUDIENCE,
                "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
            },
        )
        team = self._team(secret=None)
        assert verify_push_identity_token(forged, team, DISTINCT_ID, APP_ID, public_keys=[public_pem]) is False
